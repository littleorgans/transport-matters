from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import socket
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import httpx
import pytest

from transport_matters.overrides import Override
from transport_matters.shared_proxy.binding import ProxyRunBinding
from transport_matters.shared_proxy.manager import SharedProxyManager
from transport_matters.shared_proxy.models import OverrideScopePayload, OverrideSnapshotPayload
from transport_matters.storage.disk import DiskStorageBackend


@asynccontextmanager
async def http_origin(body: bytes = b"ok") -> AsyncIterator[str]:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        with contextlib.suppress(Exception):
            await reader.readuntil(b"\r\n\r\n")
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            + f"Content-Length: {len(body)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
            + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    assert server.sockets is not None
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()


@pytest.fixture
def short_runtime_dir() -> Path:
    path = Path(tempfile.mkdtemp(prefix="tmsp-"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


async def test_shared_proxy_subprocess_adds_removes_reverse_and_regular_modes(
    short_runtime_dir: Path,
) -> None:
    async with http_origin(b"shared-ok") as origin:
        manager = SharedProxyManager.create(
            runtime_dir=short_runtime_dir,
            ready_timeout_s=10.0,
            request_timeout_s=10.0,
            monitor_interval_s=None,
            accept_probe_timeout_s=10.0,
        )
        reverse_port = free_port()
        regular_port = free_port()
        try:
            await manager.start()
            await manager.register(
                make_binding(
                    short_runtime_dir,
                    run_id="run-reverse",
                    cli="claude",
                    port=reverse_port,
                    upstream=origin,
                )
            )
            reverse_response = await http_get(f"http://127.0.0.1:{reverse_port}/reverse")
            assert reverse_response.text == "shared-ok"

            await manager.register(
                make_binding(
                    short_runtime_dir,
                    run_id="run-regular",
                    cli="codex",
                    port=regular_port,
                    upstream=None,
                )
            )
            regular_response = await http_get(origin + "/regular", proxy_port=regular_port)
            assert regular_response.text == "shared-ok"

            await manager.set_overrides(
                OverrideScopePayload(runId="run-reverse", trackId=None),
                OverrideSnapshotPayload(
                    enabled=True,
                    overrides=(Override(kind="message_text", target="0", value="patched"),),
                ),
            )

            await manager.deregister("run-reverse")
            await assert_port_closed(reverse_port)
            await manager.deregister("run-regular")
            await assert_port_closed(regular_port)

            await manager.register(
                make_binding(
                    short_runtime_dir,
                    run_id="run-reverse-2",
                    cli="claude",
                    port=reverse_port,
                    upstream=origin,
                )
            )
            second_response = await http_get(f"http://127.0.0.1:{reverse_port}/again")
            assert second_response.text == "shared-ok"
        finally:
            await manager.close()


async def test_shared_proxy_manager_respawns_and_rehydrates_live_bindings(
    short_runtime_dir: Path,
) -> None:
    async with http_origin(b"restart-ok") as origin:
        manager = SharedProxyManager.create(
            runtime_dir=short_runtime_dir,
            ready_timeout_s=10.0,
            request_timeout_s=10.0,
            monitor_interval_s=None,
            accept_probe_timeout_s=10.0,
        )
        reverse_port = free_port()
        regular_port = free_port()
        try:
            await manager.register(
                make_binding(
                    short_runtime_dir,
                    run_id="run-reverse",
                    cli="claude",
                    port=reverse_port,
                    upstream=origin,
                )
            )
            await manager.register(
                make_binding(
                    short_runtime_dir,
                    run_id="run-regular",
                    cli="codex",
                    port=regular_port,
                    upstream=None,
                )
            )
            pid = manager.process_id
            assert pid is not None
            os.kill(pid, signal.SIGTERM)
            await wait_for_exit(manager)

            await manager.supervise()

            reverse_response = await http_get(f"http://127.0.0.1:{reverse_port}/reverse")
            regular_response = await http_get(origin + "/regular", proxy_port=regular_port)
            assert reverse_response.text == "restart-ok"
            assert regular_response.text == "restart-ok"
            assert manager.process_id != pid
        finally:
            await manager.close()


async def http_get(url: str, *, proxy_port: int | None = None) -> httpx.Response:
    proxy = f"http://127.0.0.1:{proxy_port}" if proxy_port is not None else None
    async with httpx.AsyncClient(proxy=proxy, timeout=10.0, trust_env=False) as client:
        response = await client.get(url)
    response.raise_for_status()
    return response


async def wait_for_exit(manager: SharedProxyManager) -> None:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if not manager.is_running:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("shared proxy subprocess did not exit")


async def assert_port_closed(port: int) -> None:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            return
        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.05)
    raise AssertionError(f"port {port} still accepted connections")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def make_binding(
    runtime_dir: Path,
    *,
    run_id: str,
    cli: str,
    port: int,
    upstream: str | None,
) -> ProxyRunBinding:
    return ProxyRunBinding(
        run_id=run_id,
        cli=cli,
        working_dir=runtime_dir,
        storage=DiskStorageBackend(runtime_dir / run_id),
        listen_port=port,
        upstream=upstream,
        agent_home_dir=None,
        owned_native_session_id=None,
        owned_source_descriptor=None,
    )
