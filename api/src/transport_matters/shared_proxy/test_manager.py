from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from transport_matters.overrides import Override
from transport_matters.shared_proxy.binding import ProxyRunBinding
from transport_matters.shared_proxy.control import SharedProxyControlError, SharedProxyControlServer
from transport_matters.shared_proxy.manager import (
    CONTROL_SOCKET_MAX_PATH,
    SharedProxyManager,
    SharedProxyProcessExited,
    SharedProxyRegistryError,
    _control_socket_path,
)
from transport_matters.shared_proxy.models import (
    OverrideScopePayload,
    OverrideSnapshotPayload,
    RegisterListenerRequest,
    SetOverridesRequest,
    SharedProxyControlAck,
    SharedProxyControlRequest,
    binding_payload_from_binding,
)
from transport_matters.shared_proxy.process import SharedProxyProcessExit
from transport_matters.storage.disk import DiskStorageBackend


class FakeProcess:
    def __init__(self) -> None:
        self.starts = 0
        self.running = False
        self.exit_status_value: SharedProxyProcessExit | None = None
        self.exit_on_start: SharedProxyProcessExit | None = None

    @property
    def process_id(self) -> int | None:
        return 1000 + self.starts if self.running else None

    def is_running(self) -> bool:
        return self.running

    def exit_status(self) -> SharedProxyProcessExit | None:
        return self.exit_status_value if not self.running else None

    def start(self) -> None:
        self.starts += 1
        if self.exit_on_start is not None:
            self.running = False
            self.exit_status_value = self.exit_on_start
            return
        self.running = True
        self.exit_status_value = None

    def terminate(self) -> None:
        self.running = False


class FakeControl:
    def __init__(self) -> None:
        self.requests: list[object] = []
        self.pings = 0
        self.fail_register_requests = 0
        self.fail_set_override_requests = 0

    async def ping(self) -> SharedProxyControlAck:
        self.pings += 1
        return SharedProxyControlAck()

    async def request(self, request: SharedProxyControlRequest) -> SharedProxyControlAck:
        self.requests.append(request)
        if isinstance(request, RegisterListenerRequest) and self.fail_register_requests > 0:
            self.fail_register_requests -= 1
            raise SharedProxyControlError("register_failed", "register failed")
        if isinstance(request, SetOverridesRequest) and self.fail_set_override_requests > 0:
            self.fail_set_override_requests -= 1
            raise SharedProxyControlError("overrides_failed", "overrides failed")
        return SharedProxyControlAck()


def test_binding_payload_infers_reverse_mode(tmp_path: Path) -> None:
    binding = make_binding(tmp_path, run_id="run-a", port=38101)

    payload = binding_payload_from_binding(binding)

    assert payload.mode_kind == "reverse"
    assert payload.mode_spec() == "reverse:http://example.test@127.0.0.1:38101"


@pytest.mark.parametrize(
    "module",
    [
        "transport_matters.shared_proxy.addon",
        "transport_matters.shared_proxy.control",
        "transport_matters.shared_proxy.manager",
        "transport_matters.shared_proxy.models",
        "transport_matters.shared_proxy.process",
        "transport_matters.shared_proxy.subprocess",
    ],
)
def test_shared_proxy_modules_import_in_fresh_interpreter(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


async def test_manager_registers_binding_and_rejects_duplicate_ports(tmp_path: Path) -> None:
    process = FakeProcess()
    control = FakeControl()
    manager = SharedProxyManager(process=process, control=control, monitor_interval_s=None)

    await manager.register(make_binding(tmp_path, run_id="run-a", port=38101))

    assert process.starts == 1
    assert manager.by_listen_port[38101] == "run-a"
    assert [type(request) for request in control.requests] == [RegisterListenerRequest]

    with pytest.raises(SharedProxyRegistryError):
        await manager.register(make_binding(tmp_path, run_id="run-b", port=38101))


async def test_manager_registers_multiple_runs_on_one_process(tmp_path: Path) -> None:
    process = FakeProcess()
    control = FakeControl()
    manager = SharedProxyManager(process=process, control=control, monitor_interval_s=None)

    await manager.register(make_binding(tmp_path, run_id="run-a", port=38101))
    await manager.register(make_binding(tmp_path, run_id="run-b", port=38102))

    assert process.starts == 1
    assert manager.by_listen_port == {38101: "run-a", 38102: "run-b"}
    assert [type(request) for request in control.requests] == [
        RegisterListenerRequest,
        RegisterListenerRequest,
    ]


async def test_manager_rehydrates_bindings_and_overrides_after_restart(tmp_path: Path) -> None:
    process = FakeProcess()
    control = FakeControl()
    manager = SharedProxyManager(process=process, control=control, monitor_interval_s=None)
    await manager.register(make_binding(tmp_path, run_id="run-a", port=38101))
    await manager.set_overrides(
        OverrideScopePayload(runId="run-a", trackId=None),
        OverrideSnapshotPayload(
            enabled=True,
            overrides=(Override(kind="message_text", target="0", value="patched"),),
        ),
    )
    control.requests.clear()

    process.running = False
    await manager.supervise()

    assert process.starts == 2
    assert [type(request) for request in control.requests] == [
        RegisterListenerRequest,
        SetOverridesRequest,
    ]


async def test_monitor_retries_failed_rehydrate_without_dying(tmp_path: Path) -> None:
    process = FakeProcess()
    control = FakeControl()
    manager = SharedProxyManager(
        process=process,
        control=control,
        ready_timeout_s=0.2,
        monitor_interval_s=0.01,
        monitor_max_backoff_s=0.01,
    )
    await manager.register(make_binding(tmp_path, run_id="run-a", port=38101))
    control.requests.clear()
    control.fail_register_requests = 1

    manager._start_monitor()
    process.running = False
    await wait_for_request_count(control, RegisterListenerRequest, count=1)
    await wait_for_request_count(control, RegisterListenerRequest, count=2)

    assert manager._monitor_task is not None
    assert not manager._monitor_task.done()
    await manager.close()


async def test_manager_deregisters_listener_after_ack(tmp_path: Path) -> None:
    process = FakeProcess()
    control = FakeControl()
    manager = SharedProxyManager(process=process, control=control, monitor_interval_s=None)
    await manager.register(make_binding(tmp_path, run_id="run-a", port=38101))

    await manager.deregister("run-a")

    assert "run-a" not in manager.by_run_id
    assert 38101 not in manager.by_listen_port


async def test_deregister_drops_run_overrides_before_future_rehydrate(tmp_path: Path) -> None:
    process = FakeProcess()
    control = FakeControl()
    manager = SharedProxyManager(process=process, control=control, monitor_interval_s=None)
    await manager.register(make_binding(tmp_path, run_id="run-a", port=38101))
    await manager.set_overrides(
        OverrideScopePayload(runId="run-a", trackId=None),
        OverrideSnapshotPayload(
            enabled=True,
            overrides=(Override(kind="message_text", target="0", value="patched"),),
        ),
    )
    await manager.deregister("run-a")
    control.requests.clear()

    process.running = False
    await manager.supervise()

    assert not [request for request in control.requests if isinstance(request, SetOverridesRequest)]


async def test_set_overrides_preserves_previous_snapshot_on_ack_failure(tmp_path: Path) -> None:
    process = FakeProcess()
    control = FakeControl()
    manager = SharedProxyManager(process=process, control=control, monitor_interval_s=None)
    scope = OverrideScopePayload(runId="run-a", trackId=None)
    original = OverrideSnapshotPayload(
        enabled=True,
        overrides=(Override(kind="message_text", target="0", value="original"),),
    )
    replacement = OverrideSnapshotPayload(
        enabled=True,
        overrides=(Override(kind="message_text", target="0", value="replacement"),),
    )
    await manager.set_overrides(scope, original)
    control.fail_set_override_requests = 1

    with pytest.raises(SharedProxyControlError):
        await manager.set_overrides(scope, replacement)
    process.running = False
    control.requests.clear()
    await manager.supervise()

    pushed_overrides = [
        request.payload for request in control.requests if isinstance(request, SetOverridesRequest)
    ]
    assert pushed_overrides == [original]


async def test_start_surfaces_early_process_exit(tmp_path: Path) -> None:
    process = FakeProcess()
    control = FakeControl()
    manager = SharedProxyManager(
        process=process,
        control=control,
        ready_timeout_s=0.2,
        monitor_interval_s=None,
    )

    process.exit_on_start = SharedProxyProcessExit(return_code=17, log_tail="boom")

    with pytest.raises(SharedProxyProcessExited, match=r"returncode=17.*boom"):
        await manager.start()


def test_control_socket_path_moves_long_runtime_paths_to_tmp() -> None:
    runtime_dir = Path("/very") / ("long" * 40) / "runtime" / "shared-proxy"

    control_socket = _control_socket_path(runtime_dir)

    assert len(str(control_socket)) <= CONTROL_SOCKET_MAX_PATH
    assert control_socket.name == "s.sock"


async def test_control_server_closes_idle_connection_on_read_timeout() -> None:
    socket_dir = Path(tempfile.mkdtemp(prefix=f"tmsp-{os.getpid()}-", dir="/tmp"))
    socket_path = socket_dir / "s.sock"
    handled = False

    async def handler(request: SharedProxyControlRequest) -> SharedProxyControlAck:
        nonlocal handled
        handled = True
        return SharedProxyControlAck()

    server = SharedProxyControlServer(socket_path, handler, request_timeout_s=0.01)
    await server.start()
    try:
        reader, writer = await asyncio.open_unix_connection(str(socket_path))
        assert await asyncio.wait_for(reader.read(), timeout=1.0) == b""
        assert handled is False
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
    finally:
        await server.close()
        shutil.rmtree(socket_dir, ignore_errors=True)


async def wait_for_request_count(
    control: FakeControl,
    request_type: type[object],
    *,
    count: int,
) -> None:
    deadline = asyncio.get_running_loop().time() + 1.0
    while asyncio.get_running_loop().time() < deadline:
        matches = [request for request in control.requests if isinstance(request, request_type)]
        if len(matches) >= count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"did not observe {count} {request_type.__name__} requests")


def make_binding(tmp_path: Path, *, run_id: str, port: int) -> ProxyRunBinding:
    return ProxyRunBinding(
        run_id=run_id,
        harness="claude",
        working_dir=tmp_path,
        storage=DiskStorageBackend(tmp_path / run_id),
        listen_port=port,
        upstream="http://example.test",
        agent_home_dir=None,
        owned_native_session_id=None,
        owned_source_descriptor=None,
    )
