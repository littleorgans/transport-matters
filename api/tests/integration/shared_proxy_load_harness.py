"""Opt-in Tier 2 shared-proxy load harness.

Run from api/:

    just shared-proxy-load-test --runs 50

The default repo test gate does not collect this file because it is intentionally
named outside pytest's configured collection patterns. The harness starts one shared
mitmdump subprocess, registers mixed Claude reverse and Codex regular listeners,
drives concurrent local proxy traffic through all listeners, validates run-scoped
capture indexes, measures a websocket echo path while proxy load is in flight,
and runs a sharded session-writer head-of-line probe with one poison session.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import TYPE_CHECKING, Any

import httpx
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from tests.integration.test_shared_proxy_subprocess import free_port, make_binding
from transport_matters.index.commit_dispatcher import ShardedCommitDispatcher
from transport_matters.session.ingest import EventBatch
from transport_matters.session.models import SessionRow
from transport_matters.session.writer import CommitResult
from transport_matters.shared_proxy.manager import SharedProxyManager
from transport_matters.storage.disk import DiskStorageBackend

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable


@dataclass(frozen=True)
class LoadRun:
    run_id: str
    cli: str
    listen_port: int
    storage_root: Path


@dataclass(frozen=True)
class TrafficMetrics:
    total_requests: int
    failed_requests: int
    contamination_count: int
    p95_request_ms: float
    mean_request_ms: float


@dataclass(frozen=True)
class CaptureMetrics:
    entries_total: int
    missing_entries: int
    wrong_run_entries: int


@dataclass(frozen=True)
class HeadOfLineMetrics:
    healthy_completed: int
    poison_errors: int
    healthy_completed_before_poison: bool
    p95_healthy_ms: float
    pool_usage_max: int
    pool_usage_limit: int


@dataclass(frozen=True)
class LoadMetrics:
    runs: int
    requests_per_run: int
    register_p95_ms: float
    register_mean_ms: float
    traffic: TrafficMetrics
    capture: CaptureMetrics
    terminal_ws_echo_p95_ms: float
    terminal_ws_echo_mean_ms: float
    head_of_line: HeadOfLineMetrics
    proxy_cpu_peak_percent: float
    verdict: str


def _p95(values: Iterable[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, int(len(ordered) * 0.95 + 0.999999) - 1)
    return ordered[index]


def _anthropic_request(run_id: str, seq: int) -> dict[str, Any]:
    return {
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 8,
        "metadata": {"user_id": json.dumps({"session_id": run_id, "seq": seq})},
        "messages": [{"role": "user", "content": f"{run_id}:{seq}"}],
    }


def _anthropic_response(run_id: str, seq: int) -> bytes:
    return json.dumps(
        {
            "id": f"msg-{run_id}-{seq}",
            "type": "message",
            "role": "assistant",
            "model": "claude-3-5-sonnet-20241022",
            "content": [{"type": "text", "text": f"echo:{run_id}:{seq}"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
        separators=(",", ":"),
    ).encode()


@contextlib.asynccontextmanager
async def http_origin() -> AsyncIterator[str]:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            header_bytes = await reader.readuntil(b"\r\n\r\n")
            headers = header_bytes.decode("iso-8859-1").split("\r\n")
            content_length = 0
            for header in headers[1:]:
                name, _, value = header.partition(":")
                if name.lower() == "content-length":
                    content_length = int(value.strip())
                    break
            body = await reader.readexactly(content_length) if content_length else b"{}"
            payload = json.loads(body)
            metadata = payload.get("metadata", {})
            user_id = metadata.get("user_id", "{}")
            user_meta = json.loads(user_id) if isinstance(user_id, str) else {}
            run_id = str(user_meta.get("session_id", "unknown-run"))
            seq = int(user_meta.get("seq", -1))
            response_body = _anthropic_response(run_id, seq)
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                + b"content-type: application/json\r\n"
                + f"content-length: {len(response_body)}\r\n".encode()
                + b"connection: close\r\n\r\n"
                + response_body
            )
            await writer.drain()
        except Exception as exc:
            error = json.dumps({"error": str(exc)}).encode()
            with contextlib.suppress(Exception):
                writer.write(
                    b"HTTP/1.1 500 Internal Server Error\r\n"
                    + f"content-length: {len(error)}\r\n".encode()
                    + b"connection: close\r\n\r\n"
                    + error
                )
                await writer.drain()
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    server = await asyncio.start_server(
        handle,
        "127.0.0.1",
        0,
    )
    assert server.sockets is not None
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()


async def _register_runs(
    manager: SharedProxyManager,
    runtime_dir: Path,
    origin: str,
    run_count: int,
) -> tuple[list[LoadRun], list[float]]:
    storage_root = runtime_dir / "runs"
    runs = [
        LoadRun(
            run_id=f"load-run-{index:03d}",
            cli="claude" if index % 2 == 0 else "codex",
            listen_port=free_port(),
            storage_root=storage_root / f"load-run-{index:03d}",
        )
        for index in range(run_count)
    ]
    latencies: list[float] = []

    async def register(run: LoadRun) -> None:
        started = time.perf_counter()
        await manager.register(
            make_binding(
                storage_root,
                run_id=run.run_id,
                cli=run.cli,
                port=run.listen_port,
                upstream=origin if run.cli == "claude" else None,
            )
        )
        latencies.append((time.perf_counter() - started) * 1000)

    await asyncio.gather(*(register(run) for run in runs))
    return runs, latencies


async def _drive_one_request(origin: str, run: LoadRun, seq: int) -> tuple[float, bool, bool]:
    proxy = f"http://127.0.0.1:{run.listen_port}" if run.cli == "codex" else None
    url = (
        f"https://127.0.0.1:{run.listen_port}/v1/messages"
        if run.cli == "claude"
        else f"{origin}/v1/messages"
    )
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            proxy=proxy,
            verify=False,
            trust_env=False,
            timeout=30.0,
        ) as client:
            response = await client.post(
                url,
                json=_anthropic_request(run.run_id, seq),
                headers={
                    "content-type": "application/json",
                    "anthropic-version": "2023-06-01",
                    "x-load-run-id": run.run_id,
                },
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.raise_for_status()
        expected = f"echo:{run.run_id}:{seq}"
        body = response.text
        contaminated = expected not in body
        return elapsed_ms, False, contaminated
    except Exception:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return elapsed_ms, True, False


async def _drive_traffic(
    origin: str,
    runs: list[LoadRun],
    requests_per_run: int,
) -> TrafficMetrics:
    results = await asyncio.gather(
        *(_drive_one_request(origin, run, seq) for run in runs for seq in range(requests_per_run))
    )
    latencies = [latency for latency, _failed, _contaminated in results]
    return TrafficMetrics(
        total_requests=len(results),
        failed_requests=sum(1 for _latency, failed, _contaminated in results if failed),
        contamination_count=sum(1 for _latency, _failed, contaminated in results if contaminated),
        p95_request_ms=_p95(latencies),
        mean_request_ms=mean(latencies) if latencies else 0.0,
    )


async def _validate_capture(runs: list[LoadRun], requests_per_run: int) -> CaptureMetrics:
    entries_total = 0
    missing_entries = 0
    wrong_run_entries = 0
    for run in runs:
        storage = DiskStorageBackend(run.storage_root)
        entries = await storage.read_index(limit=requests_per_run + 5, offset=0, run_id=run.run_id)
        entries_total += len(entries)
        if len(entries) < requests_per_run:
            missing_entries += requests_per_run - len(entries)
        wrong_run_entries += sum(1 for entry in entries if entry.run_id != run.run_id)
    return CaptureMetrics(
        entries_total=entries_total,
        missing_entries=missing_entries,
        wrong_run_entries=wrong_run_entries,
    )


@contextlib.asynccontextmanager
async def _websocket_echo_server() -> AsyncIterator[str]:
    async def echo(websocket: Any) -> None:
        async for message in websocket:
            await websocket.send(message)

    async with serve(echo, "127.0.0.1", 0) as server:
        assert server.sockets is not None
        port = server.sockets[0].getsockname()[1]
        yield f"ws://127.0.0.1:{port}"


async def _measure_websocket_echo(uri: str, samples: int) -> tuple[float, float]:
    latencies: list[float] = []
    async with connect(uri) as websocket:
        for index in range(samples):
            payload = f"terminal-echo-{index}"
            started = time.perf_counter()
            await websocket.send(payload)
            echoed = await websocket.recv()
            elapsed_ms = (time.perf_counter() - started) * 1000
            if echoed != payload:
                raise RuntimeError(f"websocket echo mismatch for sample {index}")
            latencies.append(elapsed_ms)
    return _p95(latencies), mean(latencies) if latencies else 0.0


def _session_row(session_id: str, run_id: str) -> SessionRow:
    now = datetime.now(UTC)
    return SessionRow(
        session_id=session_id,
        provider="claude",
        cli="claude",
        run_id=run_id,
        workspace_slug="load",
        workspace_hash="load",
        started_at=now,
        created_at=now,
        updated_at=now,
    )


def _unique_shard_session_ids(count: int, shard_count: int) -> list[str]:
    if count > shard_count:
        raise ValueError("pool_limit must be at least runs for the no-HOL probe")
    ids: list[str] = []
    used_shards: set[int] = set()
    candidate = 0
    while len(ids) < count:
        session_id = f"session-{candidate:05d}"
        shard = hash(session_id) % shard_count
        if shard not in used_shards:
            ids.append(session_id)
            used_shards.add(shard)
        candidate += 1
    return ids


async def _run_head_of_line_probe(run_count: int, pool_limit: int) -> HeadOfLineMetrics:
    active = 0
    max_active = 0
    completed_at: dict[str, float] = {}
    poison_finished_at = 0.0
    loop = asyncio.get_running_loop()
    session_ids = _unique_shard_session_ids(run_count, pool_limit)
    poison_session_id = session_ids[0]

    async def submit(batch: EventBatch) -> CommitResult:
        nonlocal active, max_active, poison_finished_at
        session_id = batch.session.session_id
        active += 1
        max_active = max(max_active, active)
        try:
            if session_id == poison_session_id:
                await asyncio.sleep(1.0)
                poison_finished_at = time.perf_counter()
                raise RuntimeError("poison session")
            await asyncio.sleep(0.02)
            completed_at[session_id] = time.perf_counter()
            return CommitResult(ok=True, session_id=session_id, committed=1, last_seq=1)
        finally:
            active -= 1

    dispatcher = ShardedCommitDispatcher(
        loop=loop,
        submit=submit,
        shard_count=pool_limit,
        queue_size=max(run_count, pool_limit),
        commit_timeout_s=2.0,
    )
    started = time.perf_counter()
    futures = [
        dispatcher.submit(
            EventBatch(session=_session_row(session_ids[index], f"load-run-{index:03d}"))
        )
        for index in range(run_count)
    ]
    results = await asyncio.gather(
        *(asyncio.wrap_future(future) for future in futures), return_exceptions=True
    )
    await dispatcher.aclose()
    healthy_latencies = [
        (finished - started) * 1000
        for session_id, finished in completed_at.items()
        if session_id != poison_session_id
    ]
    poison_errors = sum(1 for result in results if isinstance(result, RuntimeError))
    healthy_completed_before_poison = all(
        finished < poison_finished_at for finished in completed_at.values()
    )
    return HeadOfLineMetrics(
        healthy_completed=len(completed_at),
        poison_errors=poison_errors,
        healthy_completed_before_poison=healthy_completed_before_poison,
        p95_healthy_ms=_p95(healthy_latencies),
        pool_usage_max=max_active,
        pool_usage_limit=pool_limit,
    )


async def _sample_process_cpu(pid: int, stop: asyncio.Event) -> list[float]:
    samples: list[float] = []
    while not stop.is_set():
        result = await asyncio.to_thread(
            subprocess.run,
            ["ps", "-p", str(pid), "-o", "%cpu="],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        output = result.stdout.strip()
        if output:
            with contextlib.suppress(ValueError):
                samples.append(float(output))
        await asyncio.sleep(0.2)
    return samples


def _verdict(metrics: LoadMetrics) -> str:
    traffic_ok = metrics.traffic.failed_requests == 0 and metrics.traffic.contamination_count == 0
    capture_ok = metrics.capture.missing_entries == 0 and metrics.capture.wrong_run_entries == 0
    hol_ok = (
        metrics.head_of_line.healthy_completed == metrics.runs - 1
        and metrics.head_of_line.poison_errors == 1
        and metrics.head_of_line.healthy_completed_before_poison
        and metrics.head_of_line.pool_usage_max <= metrics.head_of_line.pool_usage_limit
    )
    saturated = metrics.proxy_cpu_peak_percent >= 95.0
    if traffic_ok and capture_ok and hol_ok and not saturated:
        return f"one subprocess sufficient for {metrics.runs}"
    if saturated:
        return f"saturates at ~{metrics.runs}, bounded pool recommended"
    return f"load test failed at {metrics.runs}, bounded pool recommended"


async def run_load_test(args: argparse.Namespace) -> LoadMetrics:
    runtime_dir = (
        Path(args.runtime_dir) if args.runtime_dir else Path(tempfile.mkdtemp(prefix="tmsp-load-"))
    )
    cleanup = not args.runtime_dir
    manager: SharedProxyManager | None = None
    stop_cpu = asyncio.Event()
    cpu_task: asyncio.Task[list[float]] | None = None
    previous_disable_counter = os.environ.get("TRANSPORT_MATTERS_DISABLE_TOKEN_COUNTER")
    os.environ["TRANSPORT_MATTERS_DISABLE_TOKEN_COUNTER"] = "1"
    try:
        async with http_origin() as origin:
            manager = SharedProxyManager.create(
                runtime_dir=runtime_dir,
                ready_timeout_s=15.0,
                request_timeout_s=15.0,
                monitor_interval_s=None,
                accept_probe_timeout_s=15.0,
            )
            await manager.start()
            pid = manager.process_id
            if pid is not None:
                cpu_task = asyncio.create_task(_sample_process_cpu(pid, stop_cpu))
            runs, register_latencies = await _register_runs(manager, runtime_dir, origin, args.runs)
            async with _websocket_echo_server() as echo_uri:
                traffic_task = asyncio.create_task(
                    _drive_traffic(origin, runs, args.requests_per_run)
                )
                echo_task = asyncio.create_task(
                    _measure_websocket_echo(echo_uri, args.ws_echo_samples)
                )
                traffic, (echo_p95, echo_mean) = await asyncio.gather(traffic_task, echo_task)
            capture = await _validate_capture(runs, args.requests_per_run)
            head_of_line = await _run_head_of_line_probe(args.runs, args.pool_limit)
            stop_cpu.set()
            cpu_samples = await cpu_task if cpu_task is not None else []
            metrics = LoadMetrics(
                runs=args.runs,
                requests_per_run=args.requests_per_run,
                register_p95_ms=_p95(register_latencies),
                register_mean_ms=mean(register_latencies) if register_latencies else 0.0,
                traffic=traffic,
                capture=capture,
                terminal_ws_echo_p95_ms=echo_p95,
                terminal_ws_echo_mean_ms=echo_mean,
                head_of_line=head_of_line,
                proxy_cpu_peak_percent=max(cpu_samples) if cpu_samples else 0.0,
                verdict="pending",
            )
            return LoadMetrics(**{**metrics.__dict__, "verdict": _verdict(metrics)})
    finally:
        stop_cpu.set()
        if cpu_task is not None and not cpu_task.done():
            with contextlib.suppress(asyncio.CancelledError):
                await cpu_task
        if manager is not None:
            await manager.close()
        if previous_disable_counter is None:
            os.environ.pop("TRANSPORT_MATTERS_DISABLE_TOKEN_COUNTER", None)
        else:
            os.environ["TRANSPORT_MATTERS_DISABLE_TOKEN_COUNTER"] = previous_disable_counter
        if cleanup:
            shutil.rmtree(runtime_dir, ignore_errors=True)


def _as_json(metrics: LoadMetrics) -> str:
    return json.dumps(metrics, default=lambda value: value.__dict__, indent=2, sort_keys=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tier 2 shared proxy 50-run load harness")
    parser.add_argument("--runs", type=int, default=50)
    parser.add_argument("--requests-per-run", type=int, default=2)
    parser.add_argument("--pool-limit", type=int, default=50)
    parser.add_argument("--ws-echo-samples", type=int, default=100)
    parser.add_argument("--runtime-dir", type=Path, default=None)
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    metrics = await run_load_test(args)
    print(_as_json(metrics))
    print(
        "verdict: "
        f"{metrics.verdict}; "
        f"p95_request_ms={metrics.traffic.p95_request_ms:.1f}; "
        f"proxy_cpu_peak_percent={metrics.proxy_cpu_peak_percent:.1f}; "
        f"register_p95_ms={metrics.register_p95_ms:.1f}; "
        f"terminal_ws_echo_p95_ms={metrics.terminal_ws_echo_p95_ms:.1f}; "
        f"hol_healthy={metrics.head_of_line.healthy_completed}/{metrics.runs - 1}"
    )
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
