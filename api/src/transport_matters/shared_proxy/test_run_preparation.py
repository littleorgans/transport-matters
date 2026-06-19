from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from transport_matters.captured_run_context import CapturedRunContext
from transport_matters.captured_run_dependencies import CapturedRunDependencies
from transport_matters.captured_run_models import (
    WEB_RUNTIME_EXTERNAL,
    CapturedRunProxyStartTimeout,
    CapturedRunRequest,
)
from transport_matters.cli.launch_runtime import LaunchPreparation
from transport_matters.cli.runner import ManagedClient
from transport_matters.shared_proxy.control import SharedProxyControlError
from transport_matters.shared_proxy.run_preparation import (
    SharedCapturedRunLease,
    prepare_shared_captured_run,
)

if TYPE_CHECKING:
    from pathlib import Path

    from transport_matters.shared_proxy.binding import ProxyRunBinding


class FakeSharedProxyManager:
    def __init__(self) -> None:
        self.registered: list[ProxyRunBinding] = []
        self.deregistered: list[str] = []
        self.fail_register: BaseException | None = None

    async def register(self, binding: ProxyRunBinding) -> None:
        if self.fail_register is not None:
            raise self.fail_register
        self.registered.append(binding)

    async def deregister(self, run_id: str) -> None:
        self.deregistered.append(run_id)


@pytest.mark.asyncio
async def test_prepare_shared_captured_run_registers_binding_and_lease_deregisters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    ctx = _context(tmp_path, request=request)
    monkeypatch.setattr(
        "transport_matters.shared_proxy.run_preparation.build_captured_run_context",
        lambda *args, **kwargs: ctx,
    )
    monkeypatch.setattr(
        "transport_matters.shared_proxy.run_preparation.persist_owned_session_facts",
        lambda ctx: None,
    )
    manager = FakeSharedProxyManager()

    spawn_spec, lease = await prepare_shared_captured_run(
        request,
        shared_proxy=cast("Any", manager),
        dependencies=_dependencies(),
    )

    assert spawn_spec.run_id == "run-1"
    assert spawn_spec.proxy_port == 19001
    assert len(manager.registered) == 1
    binding = manager.registered[0]
    assert binding.run_id == "run-1"
    assert binding.listen_port == 19001
    assert cast("Any", binding.storage).root == tmp_path / "storage"
    assert binding.owned_native_session_id == "native-1"
    assert binding.owned_source_descriptor == "claude:owned"
    assert binding.launch_fields["template"] == "rt"

    assert isinstance(lease, SharedCapturedRunLease)
    await lease.aclose()
    assert manager.deregistered == ["run-1"]


@pytest.mark.asyncio
async def test_prepare_shared_captured_run_preserves_explicit_home_without_runtime_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit_home = tmp_path / "explicit-home"
    request = replace(_request(tmp_path), home_dir=explicit_home)
    ctx = replace(
        _context(tmp_path, request=request),
        runtime_home_dir=None,
        runtime_home_plan=None,
    )
    monkeypatch.setattr(
        "transport_matters.shared_proxy.run_preparation.build_captured_run_context",
        lambda *args, **kwargs: ctx,
    )
    monkeypatch.setattr(
        "transport_matters.shared_proxy.run_preparation.persist_owned_session_facts",
        lambda ctx: None,
    )
    manager = FakeSharedProxyManager()

    _spawn_spec, lease = await prepare_shared_captured_run(
        request,
        shared_proxy=cast("Any", manager),
        dependencies=_dependencies(),
    )

    assert manager.registered[0].agent_home_dir == explicit_home
    await lease.aclose()


@pytest.mark.asyncio
async def test_prepare_shared_captured_run_allows_deferred_codex_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = replace(
        _request(tmp_path),
        harness="codex",
        upstream="",
        defer_session_ownership=True,
    )
    runtime_home = tmp_path / "runtime-home"
    ctx = replace(
        _context(tmp_path, request=request),
        managed_session=None,
        runtime_home_dir=runtime_home,
    )
    monkeypatch.setattr(
        "transport_matters.shared_proxy.run_preparation.build_captured_run_context",
        lambda *args, **kwargs: ctx,
    )
    monkeypatch.setattr(
        "transport_matters.shared_proxy.run_preparation.persist_owned_session_facts",
        lambda ctx: None,
    )
    manager = FakeSharedProxyManager()

    _spawn_spec, lease = await prepare_shared_captured_run(
        request,
        shared_proxy=cast("Any", manager),
        dependencies=_dependencies(),
    )

    binding = manager.registered[0]
    assert binding.agent_home_dir == runtime_home
    assert binding.owned_native_session_id is None
    assert binding.owned_source_descriptor is None
    await lease.aclose()


@pytest.mark.asyncio
async def test_shared_captured_run_lease_sync_close_is_loop_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    ctx = _context(tmp_path, request=request)
    monkeypatch.setattr(
        "transport_matters.shared_proxy.run_preparation.build_captured_run_context",
        lambda *args, **kwargs: ctx,
    )
    monkeypatch.setattr(
        "transport_matters.shared_proxy.run_preparation.persist_owned_session_facts",
        lambda ctx: None,
    )
    manager = FakeSharedProxyManager()

    _spawn_spec, lease = await prepare_shared_captured_run(
        request,
        shared_proxy=cast("Any", manager),
        dependencies=_dependencies(),
    )

    lease.close()
    await lease.aclose()
    assert manager.deregistered == []


@pytest.mark.asyncio
async def test_prepare_shared_captured_run_maps_listener_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    ctx = _context(tmp_path, request=request)
    monkeypatch.setattr(
        "transport_matters.shared_proxy.run_preparation.build_captured_run_context",
        lambda *args, **kwargs: ctx,
    )
    monkeypatch.setattr(
        "transport_matters.shared_proxy.run_preparation.persist_owned_session_facts",
        lambda ctx: None,
    )
    manager = FakeSharedProxyManager()
    manager.fail_register = SharedProxyControlError("listener_ready_timeout", "not ready")

    with pytest.raises(CapturedRunProxyStartTimeout, match="not ready"):
        await prepare_shared_captured_run(
            request,
            shared_proxy=cast("Any", manager),
            dependencies=_dependencies(),
        )

    assert manager.deregistered == []


def _request(tmp_path: Path) -> CapturedRunRequest:
    return CapturedRunRequest(
        harness="claude",
        passthrough=(),
        directory=tmp_path,
        proxy_port=None,
        web_port=None,
        upstream="https://api.anthropic.com",
        storage_dir=None,
        home_dir=None,
        client_bin=None,
        client_disabled=False,
        no_system_prompt=True,
        debug=False,
        web_runtime=WEB_RUNTIME_EXTERNAL,
        default_client_passthrough=("-p",),
        launch_fields={"request": "field"},
    )


def _context(tmp_path: Path, *, request: CapturedRunRequest) -> CapturedRunContext:
    prepared = LaunchPreparation(
        addon_traversable=tmp_path,
        mitmdump="mitmdump",
        client_path="/bin/echo",
        working_dir=tmp_path,
        proxy_port=19001,
        web_port=None,
        proxy_user_supplied=False,
        web_user_supplied=False,
        run_id="run-1",
        resolved_storage=tmp_path / "storage",
        passthrough_user=(),
    )
    client = ManagedClient(
        name="claude",
        display_name="Claude",
        argv=["/bin/echo"],
        env={},
        cwd=tmp_path,
    )

    def build_invocation(
        proxy_port: int, web_port: int | None
    ) -> tuple[list[str], dict[str, str], ManagedClient]:
        assert proxy_port == 19001
        assert web_port is None
        return [], {"TRANSPORT_MATTERS_RUN_ID": "run-1"}, client

    return CapturedRunContext(
        request=request,
        profile=cast("Any", None),
        prepared=prepared,
        managed_session=cast(
            "Any",
            SimpleNamespace(
                native_session_id="native-1",
                source_descriptor="claude:owned",
            ),
        ),
        build_invocation=build_invocation,
        resource_stack=ExitStack(),
        runtime_home_dir=tmp_path / "runtime-home",
        runtime_home_plan=cast(
            "Any",
            SimpleNamespace(
                descriptor_home=tmp_path / "runtime-home",
                launch_fields={"template": "rt"},
            ),
        ),
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
