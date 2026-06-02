"""Tests for the exchanges list endpoint."""

from typing import TYPE_CHECKING

from httpx import ASGITransport, AsyncClient

from transport_matters import addon_handlers, config
from transport_matters import breakpoint as bp
from transport_matters.flow_state import get_request_flow_state
from transport_matters.main import create_app
from transport_matters.storage import CodexTurnListSummary
from transport_matters.test_http_provisional import (
    _http_flow,
    _patch_pipeline,
    _response_body,
    _set_response,
)
from transport_matters.track_manager import get_track_manager

from .test_exchanges_support import make_index_entry

if TYPE_CHECKING:
    import pytest


class TestListExchanges:
    async def test_list_after_write_for_current_run(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from transport_matters.storage import get_storage

        monkeypatch.setenv("TRANSPORT_MATTERS_RUN_ID", "run-current")
        config.get_settings.cache_clear()
        storage = await get_storage()
        entry = make_index_entry(run_id="run-current")
        await storage.append_index(entry)

        response = await client.get("/api/exchanges")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "ex-001"

    async def test_list_hides_other_runs_by_default(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from transport_matters.storage import get_storage

        monkeypatch.setenv("TRANSPORT_MATTERS_RUN_ID", "run-current")
        config.get_settings.cache_clear()
        storage = await get_storage()
        await storage.append_index(make_index_entry("ex-old", run_id="run-old"))
        await storage.append_index(make_index_entry("ex-new", run_id="run-current"))

        response = await client.get("/api/exchanges")
        assert response.status_code == 200
        data = response.json()
        assert [row["id"] for row in data] == ["ex-new"]

    async def test_list_include_history_returns_all_runs(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from transport_matters.storage import get_storage

        monkeypatch.setenv("TRANSPORT_MATTERS_RUN_ID", "run-current")
        config.get_settings.cache_clear()
        storage = await get_storage()
        await storage.append_index(make_index_entry("ex-old", run_id="run-old"))
        await storage.append_index(make_index_entry("ex-new", run_id="run-current"))

        response = await client.get("/api/exchanges?include_history=true")
        assert response.status_code == 200
        data = response.json()
        assert [row["id"] for row in data] == ["ex-old", "ex-new"]

    async def test_list_filters_by_track_id(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from transport_matters.storage import get_storage

        monkeypatch.setenv("TRANSPORT_MATTERS_RUN_ID", "run-current")
        config.get_settings.cache_clear()
        storage = await get_storage()
        await storage.append_index(
            make_index_entry("parent", run_id="run-current").model_copy(
                update={
                    "track_id": "run-current",
                    "track_role": "parent",
                }
            )
        )
        await storage.append_index(
            make_index_entry("subagent-a", run_id="run-current").model_copy(
                update={
                    "track_id": "agent-a",
                    "parent_track_id": "run-current",
                    "track_display_name": "research-a",
                    "track_role": "subagent",
                }
            )
        )
        await storage.append_index(
            make_index_entry("subagent-b", run_id="run-current").model_copy(
                update={
                    "track_id": "agent-b",
                    "parent_track_id": "run-current",
                    "track_display_name": "research-b",
                    "track_role": "subagent",
                }
            )
        )

        response = await client.get("/api/exchanges", params={"track_id": "agent-a"})

        assert response.status_code == 200
        assert [entry["id"] for entry in response.json()] == ["subagent-a"]

    async def test_list_mixed_providers_respects_run_scope_and_history(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from transport_matters.storage import get_storage

        monkeypatch.setenv("TRANSPORT_MATTERS_RUN_ID", "run-current")
        config.get_settings.cache_clear()
        storage = await get_storage()
        await storage.append_index(make_index_entry("anth-old", run_id="run-old"))
        await storage.append_index(
            make_index_entry("codex-old", run_id="run-old").model_copy(
                update={
                    "provider": "codex",
                    "model": "codex/gpt-5-codex",
                }
            )
        )
        await storage.append_index(make_index_entry("anth-current", run_id="run-current"))
        await storage.append_index(
            make_index_entry("codex-current", run_id="run-current").model_copy(
                update={
                    "provider": "codex",
                    "model": "codex/gpt-5-codex",
                }
            )
        )

        response = await client.get("/api/exchanges")
        assert response.status_code == 200
        data = response.json()
        assert [(row["id"], row["provider"]) for row in data] == [
            ("anth-current", "anthropic"),
            ("codex-current", "codex"),
        ]

        history = await client.get("/api/exchanges?include_history=true")
        assert history.status_code == 200
        history_data = history.json()
        assert [(row["id"], row["run_id"], row["provider"]) for row in history_data] == [
            ("anth-old", "run-old", "anthropic"),
            ("codex-old", "run-old", "codex"),
            ("anth-current", "run-current", "anthropic"),
            ("codex-current", "run-current", "codex"),
        ]

    async def test_list_surfaces_codex_turn_summary_when_present(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from transport_matters.storage import get_storage

        monkeypatch.setenv("TRANSPORT_MATTERS_RUN_ID", "run-current")
        config.get_settings.cache_clear()
        storage = await get_storage()
        await storage.append_index(
            make_index_entry("codex-current", run_id="run-current").model_copy(
                update={
                    "provider": "codex",
                    "model": "codex/gpt-5-codex",
                    "codex_turn": CodexTurnListSummary(
                        turn_index=3,
                        message_range_start=8,
                        message_range_end=11,
                        status="completed",
                        terminal_cause="response_completed",
                        stop_reason="completed",
                        text_chars=144,
                        tool_calls=1,
                    ),
                }
            )
        )

        response = await client.get("/api/exchanges")
        assert response.status_code == 200
        data = response.json()
        assert data[0]["id"] == "codex-current"
        assert data[0]["codex_turn"] == {
            "turn_index": 3,
            "message_range_start": 8,
            "message_range_end": 11,
            "status": "completed",
            "terminal_cause": "response_completed",
            "stop_reason": "completed",
            "text_chars": 144,
            "tool_calls": 1,
        }

    async def test_list_recovers_http_provisional_row_through_finalize(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRANSPORT_MATTERS_RUN_ID", "run-http")
        config.get_settings.cache_clear()
        bp.disarm()
        bp._paused.clear()
        get_track_manager()._runs.clear()
        _patch_pipeline(monkeypatch)
        flow = _http_flow("flow-http-index-recovery")

        await addon_handlers.handle_http_request(flow, None)

        state = get_request_flow_state(flow)
        assert state is not None
        exchange_id = state.provisional_exchange_id
        assert exchange_id is not None

        provisional_response = await client.get("/api/exchanges")
        assert provisional_response.status_code == 200
        provisional_rows = [row for row in provisional_response.json() if row["id"] == exchange_id]
        assert len(provisional_rows) == 1
        provisional = provisional_rows[0]
        assert provisional["res"] is None
        assert provisional["req"]["messages_count"] == 1
        assert provisional["pipeline"] == {
            "overrides_applied": [],
            "chars_before": 100,
            "chars_after": 80,
            "tokens_before": None,
            "tokens_after": None,
        }

        mid_flow_response = await client.get("/api/exchanges")
        assert mid_flow_response.status_code == 200
        mid_flow_rows = [row for row in mid_flow_response.json() if row["id"] == exchange_id]
        assert len(mid_flow_rows) == 1
        assert mid_flow_rows[0]["res"] is None
        assert mid_flow_rows[0]["req"] == provisional["req"]

        _set_response(flow, _response_body(text="index recovery final"))
        await addon_handlers.handle_response(flow, None)

        finalized_response = await client.get("/api/exchanges")
        assert finalized_response.status_code == 200
        finalized_rows = [row for row in finalized_response.json() if row["id"] == exchange_id]
        assert len(finalized_rows) == 1
        finalized = finalized_rows[0]
        assert finalized["res"] is not None
        assert finalized["res"]["stop_reason"] == "end_turn"
        assert finalized["res"]["text_chars"] == len("index recovery final")
        assert finalized["req"] == provisional["req"]


class TestListExchangesStorageFailure:
    async def test_storage_exception_returns_500(self) -> None:
        """When storage.read_index() raises, the endpoint returns 500 with a structured error."""
        from unittest.mock import AsyncMock

        from transport_matters.storage import get_storage

        broken_backend = AsyncMock()
        broken_backend.read_index.side_effect = RuntimeError("disk on fire")

        app = create_app()
        app.dependency_overrides[get_storage] = lambda: broken_backend

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/exchanges")

        assert response.status_code == 500
        data = response.json()
        assert "detail" in data
        assert "Failed to read exchange index" in data["detail"]
