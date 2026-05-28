from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest

from transport_matters import broadcast
from transport_matters.codex import exchange as codex_exchange
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
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = _Headers(headers)


class _Flow:
    def __init__(self, headers: dict[str, str]) -> None:
        self.id = "flow-codex-unparsed"
        self.metadata: dict[str, object] = {}
        self.request = _Request(headers)


@pytest.fixture(autouse=True)
def _reset_runtime_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None]:
    yield from reset_exchange_recorder_runtime_state(tmp_path, monkeypatch)


async def test_persist_unparsed_codex_exchange_records_raw_and_version() -> None:
    raw = b'{"model": "gpt-9-codex", "weird": true}'
    flow = cast(
        "http.HTTPFlow",
        _Flow({"user-agent": "codex_cli_rs/0.5.0 (Mac OS 15.0; arm64)"}),
    )
    events = broadcast.subscribe()

    await codex_exchange._persist_unparsed_codex_exchange(flow, raw)

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.provider == "codex"

    artifacts = await storage.read_exchange(entry.id)
    assert artifacts.request_raw == raw
    assert artifacts.request_ir is not None
    extras = artifacts.request_ir.provider_extras
    assert extras["type"] == "transport.parse_failure"
    assert extras["client_version"] == "codex_cli_rs/0.5.0"
    assert artifacts.request_ir.model == "gpt-9-codex"

    event = json.loads(events.get_nowait())
    assert event["type"] == "exchange"
    assert event["id"] == entry.id
    assert event["flow_id"] == flow.id


async def test_persist_unparsed_codex_exchange_skips_when_frame_missing() -> None:
    flow = cast("http.HTTPFlow", _Flow({}))

    await codex_exchange._persist_unparsed_codex_exchange(flow, b"")

    storage = await get_storage()
    assert await storage.read_index(limit=10, offset=0) == []


async def test_persist_unparsed_codex_exchange_is_exception_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = cast("http.HTTPFlow", _Flow({}))

    async def boom(*args: object, **kwargs: object) -> bool:
        raise RuntimeError("storage exploded")

    monkeypatch.setattr(codex_exchange, "_persist_exchange", boom)

    await codex_exchange._persist_unparsed_codex_exchange(flow, b"{}")

    storage = await get_storage()
    assert await storage.read_index(limit=10, offset=0) == []
