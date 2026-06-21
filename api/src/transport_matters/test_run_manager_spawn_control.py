from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

from transport_matters.captured_run import (
    WEB_RUNTIME_EMBEDDED,
    CapturedRunDependencies,
    CapturedRunHarness,
    CapturedRunLease,
    CapturedRunRequest,
    CapturedRunSpawnSpec,
)
from transport_matters.run_manager import RunManager, RunManagerError, SpawnRun
from transport_matters.test_run_manager import resolved_worktree

CLAUDE_HARNESS: CapturedRunHarness = "claude"


@dataclass
class FakeLease:
    closed: bool = False

    def close(self) -> None:
        self.closed = True


def _dependencies(check_session_store: Any = None) -> CapturedRunDependencies:
    return CapturedRunDependencies(
        require_addon=lambda: Path("addon.py"),
        resolve_mitmdump=lambda: "mitmdump",
        which=lambda *_args, **_kwargs: "fake",
        port_in_use=lambda _port: False,
        allocate_port_pair=lambda: (8787, 8788),
        inject_system_prompt=lambda passthrough, **_kwargs: list(passthrough),
        user_supplied_system_prompt=lambda _args: False,
        check_session_store=check_session_store or (lambda: None),
    )


def _prepared_without_client(
    request: CapturedRunRequest, tmp_path: Path
) -> tuple[CapturedRunSpawnSpec, CapturedRunLease]:
    return (
        CapturedRunSpawnSpec(
            run_id=f"run-{id(request)}",
            working_dir=cast("Path", request.directory),
            storage_dir=tmp_path,
            proxy_port=8787,
            web_port=None,
            mitmdump_log=tmp_path / "mitmdump.log",
            client=None,
            launch_env={},
            managed_session=None,
            harness=request.harness,
        ),
        cast("CapturedRunLease", FakeLease()),
    )


async def test_spawn_admission_control_bounds_keyless_prepare_work(tmp_path: Path) -> None:
    limit = 2
    active = 0
    calls = 0
    max_active = 0
    lock = threading.Lock()
    first_wave_entered = threading.Event()
    release = threading.Event()

    def prepare(
        request: CapturedRunRequest, **_kwargs: object
    ) -> tuple[CapturedRunSpawnSpec, CapturedRunLease]:
        nonlocal active, calls, max_active
        with lock:
            active += 1
            calls += 1
            max_active = max(max_active, active)
            if active == limit:
                first_wave_entered.set()
        release.wait(timeout=2)
        with lock:
            active -= 1
        return _prepared_without_client(request, tmp_path)

    manager = RunManager(
        dependencies=_dependencies(),
        prepare_run=prepare,
        spawn_concurrency=limit,
    )
    tasks = [
        asyncio.create_task(
            manager.spawn(
                SpawnRun(
                    harness=CLAUDE_HARNESS,
                    resolved_worktree=resolved_worktree(tmp_path),
                    web_runtime=WEB_RUNTIME_EMBEDDED,
                )
            )
        )
        for _ in range(8)
    ]

    assert await asyncio.to_thread(first_wave_entered.wait, 2)
    await asyncio.sleep(0.05)
    assert calls == limit
    release.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert max_active <= limit
    assert all(isinstance(result, RunManagerError) for result in results)


async def test_session_store_preflight_runs_off_loop_and_caches_success(
    tmp_path: Path,
) -> None:
    loop_thread = threading.get_ident()
    check_threads: list[int] = []

    def check_session_store() -> str | None:
        check_threads.append(threading.get_ident())
        return None

    def prepare(
        request: CapturedRunRequest, **_kwargs: object
    ) -> tuple[CapturedRunSpawnSpec, CapturedRunLease]:
        return _prepared_without_client(request, tmp_path)

    manager = RunManager(
        dependencies=_dependencies(check_session_store),
        prepare_run=prepare,
    )
    results = await asyncio.gather(
        *[
            manager.spawn(
                SpawnRun(
                    harness=CLAUDE_HARNESS,
                    resolved_worktree=resolved_worktree(tmp_path),
                    web_runtime=WEB_RUNTIME_EMBEDDED,
                )
            )
            for _ in range(6)
        ],
        return_exceptions=True,
    )

    assert all(isinstance(result, RunManagerError) for result in results)
    assert len(check_threads) == 1
    assert check_threads[0] != loop_thread


async def test_session_store_preflight_does_not_cache_failures(tmp_path: Path) -> None:
    calls = 0

    def check_session_store() -> str | None:
        nonlocal calls
        calls += 1
        return "down" if calls == 1 else None

    def prepare(
        request: CapturedRunRequest, **_kwargs: object
    ) -> tuple[CapturedRunSpawnSpec, CapturedRunLease]:
        return _prepared_without_client(request, tmp_path)

    manager = RunManager(
        dependencies=_dependencies(check_session_store),
        prepare_run=prepare,
    )

    with pytest.raises(RunManagerError) as first:
        await manager.spawn(
            SpawnRun(
                harness=CLAUDE_HARNESS,
                resolved_worktree=resolved_worktree(tmp_path),
                web_runtime=WEB_RUNTIME_EMBEDDED,
            )
        )
    with pytest.raises(RunManagerError) as second:
        await manager.spawn(
            SpawnRun(
                harness=CLAUDE_HARNESS,
                resolved_worktree=resolved_worktree(tmp_path),
                web_runtime=WEB_RUNTIME_EMBEDDED,
            )
        )

    assert first.value.code == "session_store_unavailable"
    assert second.value.code == "launch_failed"
    assert calls == 2


async def test_unsupported_harness_rejects_before_preflight_and_admission(tmp_path: Path) -> None:
    calls = 0
    invalid_phase = True
    release_preflight = threading.Event()
    prepare_started = threading.Event()

    def check_session_store() -> str | None:
        nonlocal calls
        calls += 1
        if invalid_phase:
            release_preflight.wait(timeout=1)
        return None

    def prepare(
        request: CapturedRunRequest, **_kwargs: object
    ) -> tuple[CapturedRunSpawnSpec, CapturedRunLease]:
        prepare_started.set()
        return _prepared_without_client(request, tmp_path)

    manager = RunManager(
        dependencies=_dependencies(check_session_store),
        prepare_run=prepare,
        spawn_concurrency=1,
    )
    invalid_task = asyncio.create_task(
        manager.spawn(
            SpawnRun(
                harness=cast("Any", "not-a-harness"), resolved_worktree=resolved_worktree(tmp_path)
            )
        )
    )
    await asyncio.sleep(0.05)
    invalid_preflight_calls = calls
    invalid_phase = False
    valid_task = asyncio.create_task(
        manager.spawn(
            SpawnRun(
                harness=CLAUDE_HARNESS,
                resolved_worktree=resolved_worktree(tmp_path),
                web_runtime=WEB_RUNTIME_EMBEDDED,
            )
        )
    )

    try:
        valid_reached_prepare = await asyncio.to_thread(prepare_started.wait, 0.3)
    finally:
        release_preflight.set()
    invalid_result, valid_result = await asyncio.gather(
        invalid_task, valid_task, return_exceptions=True
    )

    assert valid_reached_prepare
    assert isinstance(invalid_result, RunManagerError)
    assert invalid_result.code == "unsupported_harness"
    assert isinstance(valid_result, RunManagerError)
    assert valid_result.code == "launch_failed"
    assert invalid_preflight_calls == 0
    assert calls == 1


async def test_invalid_cwd_rejects_before_session_store_preflight(tmp_path: Path) -> None:
    calls = 0

    def check_session_store() -> str | None:
        nonlocal calls
        calls += 1
        return None

    manager = RunManager(dependencies=_dependencies(check_session_store))

    with pytest.raises(RunManagerError) as exc:
        await manager.spawn(
            SpawnRun(
                harness=CLAUDE_HARNESS, resolved_worktree=resolved_worktree(tmp_path / "missing")
            )
        )

    assert exc.value.code == "invalid_cwd"
    assert calls == 0
