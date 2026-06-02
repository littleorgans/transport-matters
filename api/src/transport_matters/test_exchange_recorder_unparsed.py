from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest

from transport_matters import broadcast
from transport_matters import exchange_recorder as recorder
from transport_matters.adapters.anthropic import AnthropicAdapter
from transport_matters.storage import get_storage
from transport_matters.test_exchange_recorder_support import (
    reset_exchange_recorder_runtime_state,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from mitmproxy import http


class _Headers:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = {name.lower(): value for name, value in values.items()}

    def get(self, name: str, default: str | None = None) -> str | None:
        return self._values.get(name.lower(), default)


class _Request:
    def __init__(self, *, raw_content: bytes, headers: dict[str, str]) -> None:
        self.raw_content = raw_content
        self.content = raw_content
        self.headers = _Headers(headers)

    def get_text(self) -> str:
        return self.raw_content.decode("utf-8", errors="replace")


class _Flow:
    def __init__(self, *, raw_content: bytes, headers: dict[str, str]) -> None:
        self.id = "flow-unparsed"
        self.metadata: dict[str, object] = {}
        self.request = _Request(raw_content=raw_content, headers=headers)


@pytest.fixture(autouse=True)
def _reset_runtime_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    yield from reset_exchange_recorder_runtime_state(tmp_path, monkeypatch)


async def test_persist_unparsed_http_exchange_records_raw_and_version() -> None:
    raw = b'{"model": "claude-opus-9", "weird": true}'
    flow = cast(
        "http.HTTPFlow",
        _Flow(
            raw_content=raw,
            headers={"user-agent": "claude-cli/2.1.154 (external, cli)"},
        ),
    )
    adapter = AnthropicAdapter()
    events = broadcast.subscribe()

    await recorder._persist_unparsed_http_exchange(flow, adapter, codex_http=False)

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.provider == adapter.name

    artifacts = await storage.read_exchange(entry.id)
    # Raw bytes preserved verbatim for inspection.
    assert artifacts.request_raw == raw
    assert artifacts.request_ir is not None
    extras = artifacts.request_ir.provider_extras
    assert extras["type"] == "transport.parse_failure"
    assert extras["client_version"] == "claude-cli/2.1.154"
    # Best-effort model recovered from the raw JSON.
    assert artifacts.request_ir.model == "claude-opus-9"

    event = json.loads(events.get_nowait())
    assert event["type"] == "exchange"
    assert event["id"] == entry.id
    assert event["flow_id"] == flow.id


async def test_persist_unparsed_http_exchange_falls_back_model_when_no_json() -> None:
    raw = b"\x00\x01 not json at all"
    flow = cast(
        "http.HTTPFlow",
        _Flow(raw_content=raw, headers={}),
    )
    adapter = AnthropicAdapter()

    await recorder._persist_unparsed_http_exchange(flow, adapter, codex_http=False)

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    artifacts = await storage.read_exchange(entries[0].id)
    assert artifacts.request_raw == raw
    assert artifacts.request_ir is not None
    assert artifacts.request_ir.model == f"{adapter.name}/unparsed"
    # Unknown client version is omitted, never a stray key with a bad value.
    assert "client_version" not in artifacts.request_ir.provider_extras


async def test_persist_unparsed_http_exchange_is_exception_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = cast(
        "http.HTTPFlow",
        _Flow(raw_content=b"{}", headers={}),
    )
    adapter = AnthropicAdapter()

    async def boom(*args: object, **kwargs: object) -> bool:
        raise RuntimeError("storage exploded")

    monkeypatch.setattr(recorder, "_persist_exchange", boom)

    # A recording failure must never propagate out of the proxy hook.
    await recorder._persist_unparsed_http_exchange(flow, adapter, codex_http=False)

    storage = await get_storage()
    assert await storage.read_index(limit=10, offset=0) == []
