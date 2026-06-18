from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from transport_matters import addon_handlers
from transport_matters import config as config_module
from transport_matters._exchange_recorder_http_support import _make_state
from transport_matters.addon_runtime import build_proxy_run_binding
from transport_matters.config import Settings
from transport_matters.counting import get_recent_auth
from transport_matters.flow_state import get_request_flow_state
from transport_matters.storage import get_storage, init_storage, reset_storage
from transport_matters.storage.disk import DiskStorageBackend

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from mitmproxy import http

    from transport_matters.ir import InternalRequest


class _Request:
    path = "/v1/messages"

    def __init__(self) -> None:
        self.headers = {"x-api-key": "binding-key"}
        self.text = "{}"

    def set_text(self, text: str) -> None:
        self.text = text


class _Flow:
    def __init__(self) -> None:
        self.id = "flow-binding"
        self.metadata: dict[str, object] = {}
        self.request = _Request()


@pytest.fixture
def _isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    reset_storage()
    init_storage(root=tmp_path / "global")
    monkeypatch.setenv("TRANSPORT_MATTERS_RUN_ID", "run-global")
    config_module.get_settings.cache_clear()
    yield
    reset_storage()
    config_module.get_settings.cache_clear()


async def test_binding_routes_http_capture_without_global_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _isolated_storage: None,
) -> None:
    state = _make_state()
    binding_storage = DiskStorageBackend(root=tmp_path / "binding")
    binding = build_proxy_run_binding(
        Settings(
            run_id="run-binding",
            harness="claude",
            cwd=tmp_path / "workspace",
            proxy_port=9191,
            storage_dir=tmp_path / "binding",
            breakpoint_skip_models=["claude"],
        ),
        binding_storage,
    )
    flow = cast("http.HTTPFlow", _Flow())
    pipeline_run_ids: list[str | None] = []

    async def fake_parse(
        parse_flow: http.HTTPFlow,
        adapter: object,
    ) -> tuple[bytes, InternalRequest]:
        assert parse_flow is flow
        assert adapter is state.adapter
        return state.raw_request, state.request_ir

    async def fake_pipeline(
        ir: InternalRequest,
        flow_id: str,
        run_id: str | None,
    ) -> tuple[InternalRequest, None, None]:
        pipeline_run_ids.append(run_id)
        return state.curated_request_ir, None, None

    monkeypatch.setattr(addon_handlers, "get_adapter", lambda _flow: state.adapter)
    monkeypatch.setattr(addon_handlers, "parse_request_ir", fake_parse)
    monkeypatch.setattr(addon_handlers, "run_pipeline", fake_pipeline)

    await addon_handlers.handle_http_request(flow, None, binding)

    request_state = get_request_flow_state(flow)
    assert request_state is not None
    assert request_state.run_id == "run-binding"
    assert request_state.listen_port == 9191
    assert pipeline_run_ids == ["run-binding"]
    assert get_recent_auth(binding=binding) == {"x-api-key": "binding-key"}

    binding_entries = await binding_storage.read_index(limit=10, offset=0)
    assert [entry.run_id for entry in binding_entries] == ["run-binding"]

    global_entries = await (await get_storage()).read_index(limit=10, offset=0)
    assert global_entries == []
