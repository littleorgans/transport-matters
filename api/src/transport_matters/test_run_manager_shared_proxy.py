from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from transport_matters.captured_run_dependencies import CapturedRunDependencies
from transport_matters.captured_run_models import (
    WEB_RUNTIME_EMBEDDED,
    WEB_RUNTIME_EXTERNAL,
    CapturedRunRequest,
    CapturedRunSpawnSpec,
)
from transport_matters.run_manager import RunManager, RunManagerError, SpawnRun

if TYPE_CHECKING:
    from pathlib import Path


class FakeLease:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_run_manager_routes_external_runs_to_shared_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    shared_lease = FakeLease()

    async def fake_prepare_shared(
        request: CapturedRunRequest,
        *,
        shared_proxy: object,
        dependencies: CapturedRunDependencies,
    ) -> tuple[CapturedRunSpawnSpec, FakeLease]:
        calls.append(f"{request.web_runtime}:{request.harness}")
        return _spawn_spec(tmp_path, run_id="shared-run"), shared_lease

    def forbidden_prepare(
        request: CapturedRunRequest,
        **_: object,
    ) -> tuple[CapturedRunSpawnSpec, FakeLease]:
        raise AssertionError("per-run prepare should not be used for external runs")

    monkeypatch.setattr(
        "transport_matters.run_manager.prepare_shared_captured_run",
        fake_prepare_shared,
    )
    manager = RunManager(
        dependencies=_dependencies(),
        prepare_run=forbidden_prepare,
        shared_proxy_manager=cast("Any", object()),
    )

    spec, lease = await manager._prepare_request(
        manager._validate_spawn_request(
            SpawnRun(harness="claude", cwd=tmp_path, web_runtime=WEB_RUNTIME_EXTERNAL)
        )
    )

    assert spec.run_id == "shared-run"
    assert lease is shared_lease
    assert calls == ["external:claude"]


@pytest.mark.asyncio
async def test_run_manager_keeps_embedded_runs_on_per_run_preparation(tmp_path: Path) -> None:
    calls: list[str] = []
    embedded_lease = FakeLease()

    def prepare_run(
        request: CapturedRunRequest,
        **_: object,
    ) -> tuple[CapturedRunSpawnSpec, FakeLease]:
        calls.append(f"{request.web_runtime}:{request.harness}")
        return _spawn_spec(tmp_path, run_id="embedded-run"), embedded_lease

    manager = RunManager(
        dependencies=_dependencies(),
        prepare_run=prepare_run,
        shared_proxy_manager=None,
        shared_proxy_unavailable_reason="startup failed",
    )

    spec, lease = await manager._prepare_request(
        manager._validate_spawn_request(
            SpawnRun(harness="claude", cwd=tmp_path, web_runtime=WEB_RUNTIME_EMBEDDED)
        )
    )

    assert spec.run_id == "embedded-run"
    assert lease is embedded_lease
    assert calls == ["embedded:claude"]


@pytest.mark.asyncio
async def test_run_manager_fails_external_when_shared_proxy_unavailable(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def forbidden_prepare(
        request: CapturedRunRequest,
        **_: object,
    ) -> tuple[CapturedRunSpawnSpec, FakeLease]:
        calls.append(request.web_runtime)
        raise AssertionError("per-run prepare should not be used for degraded external runs")

    manager = RunManager(
        dependencies=_dependencies(),
        prepare_run=forbidden_prepare,
        shared_proxy_manager=None,
        shared_proxy_unavailable_reason="mitmdump missing",
    )

    with pytest.raises(RunManagerError) as exc_info:
        await manager._prepare_request(
            manager._validate_spawn_request(
                SpawnRun(harness="claude", cwd=tmp_path, web_runtime=WEB_RUNTIME_EXTERNAL)
            )
        )

    assert exc_info.value.code == "proxy_start_timeout"
    assert str(exc_info.value) == "shared proxy unavailable: mitmdump missing"
    assert calls == []


@pytest.mark.asyncio
async def test_run_manager_never_falls_back_to_per_run_for_external_runs(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def forbidden_prepare(
        request: CapturedRunRequest,
        **_: object,
    ) -> tuple[CapturedRunSpawnSpec, FakeLease]:
        calls.append(request.web_runtime)
        raise AssertionError("per-run prepare should not be used for external runs")

    manager = RunManager(
        dependencies=_dependencies(),
        prepare_run=forbidden_prepare,
        shared_proxy_manager=None,
    )

    with pytest.raises(RunManagerError) as exc_info:
        await manager._prepare_request(
            manager._validate_spawn_request(
                SpawnRun(harness="claude", cwd=tmp_path, web_runtime=WEB_RUNTIME_EXTERNAL)
            )
        )

    assert exc_info.value.code == "proxy_start_timeout"
    assert str(exc_info.value) == (
        "shared proxy unavailable: shared proxy manager is not configured"
    )
    assert calls == []


def _spawn_spec(tmp_path: Path, *, run_id: str) -> CapturedRunSpawnSpec:
    return CapturedRunSpawnSpec(
        run_id=run_id,
        working_dir=tmp_path,
        storage_dir=tmp_path / run_id,
        proxy_port=19001,
        web_port=None,
        mitmdump_log=tmp_path / run_id / "mitmdump.log",
        client=None,
        launch_env={},
        managed_session=None,
        harness="claude",
    )


def _dependencies() -> CapturedRunDependencies:
    return CapturedRunDependencies(
        require_addon=lambda: cast("Any", None),
        resolve_mitmdump=lambda: "mitmdump",
        which=lambda name: f"/bin/{name}",
        port_in_use=lambda port: False,
        allocate_port_pair=lambda: (19001, 19002),
        inject_system_prompt=lambda *args, **kwargs: [],
        user_supplied_system_prompt=lambda args: False,
        check_session_store=lambda: None,
    )
