from __future__ import annotations

import json

import pytest

from transport_matters.codex.session_metadata import (
    codex_session_id_from_header_lookup,
    codex_session_id_from_request_metadata,
    codex_thread_id_from_header_lookup,
    codex_turn_id_from_header_lookup,
)
from transport_matters.ir import RequestMetadata


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        (RequestMetadata(session_id="sess-meta"), "sess-meta"),
        (
            RequestMetadata(provider_metadata={"session_id": "sess-provider"}),
            "sess-provider",
        ),
        (
            RequestMetadata(provider_metadata={"sessionId": "sess-provider-camel"}),
            "sess-provider-camel",
        ),
        (
            RequestMetadata(
                provider_metadata={"x-codex-turn-metadata": json.dumps({"session_id": "sess-turn"})}
            ),
            "sess-turn",
        ),
    ],
)
def test_codex_session_id_from_request_metadata_supports_current_sources(
    metadata: RequestMetadata,
    expected: str,
) -> None:
    assert codex_session_id_from_request_metadata(metadata) == expected


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"session-id": "sess-header", "thread-id": "thread-header"}, "sess-header"),
        ({"session-id": "[redacted]", "thread-id": "thread-header"}, "thread-header"),
        ({"thread-id": "thread-header"}, "thread-header"),
        ({"session_id": "legacy-session", "thread_id": "legacy-thread"}, None),
    ],
)
def test_codex_session_id_from_headers_uses_current_wire_headers(
    headers: dict[str, str],
    expected: str | None,
) -> None:
    assert codex_session_id_from_header_lookup(headers.get) == expected


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"thread-id": "thread-header"}, "thread-header"),
        (
            {"thread-id": "thread-header", "thread_id": "legacy-thread"},
            "thread-header",
        ),
        ({"thread_id": "legacy-thread"}, None),
    ],
)
def test_codex_thread_id_from_headers_uses_current_wire_header(
    headers: dict[str, str],
    expected: str | None,
) -> None:
    assert codex_thread_id_from_header_lookup(headers.get) == expected


def test_codex_turn_id_from_headers_parses_current_turn_metadata() -> None:
    headers = {
        "x-codex-turn-metadata": json.dumps(
            {"session_id": "sess-turn", "thread_id": "thread-turn", "turn_id": "turn-1"}
        )
    }

    assert codex_turn_id_from_header_lookup(headers.get) == "turn-1"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"x-codex-turn-metadata": ""},
        {"x-codex-turn-metadata": "not-json"},
        {"x-codex-turn-metadata": json.dumps([])},
        (
            {
                "x-codex-turn-metadata": json.dumps(
                    {"session_id": "sess-turn", "thread_id": "thread-turn"}
                )
            }
        ),
        {"x-codex-turn-metadata": json.dumps({"turn_id": ""})},
    ],
)
def test_codex_turn_id_from_headers_treats_missing_or_malformed_metadata_as_lossy(
    headers: dict[str, str],
) -> None:
    assert codex_turn_id_from_header_lookup(headers.get) is None
