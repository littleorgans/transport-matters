from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from transport_matters.overrides import Override
from transport_matters.shared_proxy.binding import ProxyRunBinding
from transport_matters.shared_proxy.manager import SharedProxyManager, SharedProxyRegistryError
from transport_matters.shared_proxy.models import (
    OverrideScopePayload,
    OverrideSnapshotPayload,
    RegisterListenerRequest,
    SetOverridesRequest,
    SharedProxyControlAck,
    SharedProxyControlRequest,
    binding_payload_from_binding,
)
from transport_matters.storage.disk import DiskStorageBackend


class FakeProcess:
    def __init__(self) -> None:
        self.starts = 0
        self.running = False

    @property
    def process_id(self) -> int | None:
        return 1000 + self.starts if self.running else None

    def is_running(self) -> bool:
        return self.running

    def start(self) -> None:
        self.starts += 1
        self.running = True

    def terminate(self) -> None:
        self.running = False


class FakeControl:
    def __init__(self) -> None:
        self.ready_calls = 0
        self.requests: list[object] = []

    async def ping(self) -> SharedProxyControlAck:
        return SharedProxyControlAck()

    async def wait_until_ready(self, *, timeout_s: float) -> None:
        self.ready_calls += 1

    async def request(self, request: SharedProxyControlRequest) -> SharedProxyControlAck:
        self.requests.append(request)
        return SharedProxyControlAck()


def test_binding_payload_infers_reverse_mode(tmp_path: Path) -> None:
    binding = make_binding(tmp_path, run_id="run-a", port=38101)

    payload = binding_payload_from_binding(binding)

    assert payload.mode_kind == "reverse"
    assert payload.mode_spec() == "reverse:http://example.test@127.0.0.1:38101"


@pytest.mark.parametrize(
    "module",
    [
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


async def test_manager_deregisters_listener_after_ack(tmp_path: Path) -> None:
    process = FakeProcess()
    control = FakeControl()
    manager = SharedProxyManager(process=process, control=control, monitor_interval_s=None)
    await manager.register(make_binding(tmp_path, run_id="run-a", port=38101))

    await manager.deregister("run-a")

    assert "run-a" not in manager.by_run_id
    assert 38101 not in manager.by_listen_port


def make_binding(tmp_path: Path, *, run_id: str, port: int) -> ProxyRunBinding:
    return ProxyRunBinding(
        run_id=run_id,
        cli="claude",
        working_dir=tmp_path,
        storage=DiskStorageBackend(tmp_path / run_id),
        listen_port=port,
        upstream="http://example.test",
        agent_home_dir=None,
        owned_native_session_id=None,
        owned_source_descriptor=None,
    )
