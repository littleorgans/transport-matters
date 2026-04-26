from __future__ import annotations

import json

import pytest

from manicure.codex.session_metadata import (
    codex_session_id_from_header_lookup,
    codex_session_id_from_request_metadata,
)
from manicure.ir import RequestMetadata


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
                provider_metadata={
                    "x-codex-turn-metadata": json.dumps({"session_id": "sess-turn"})
                }
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
        ({"x-codex-session": "sess-header"}, "sess-header"),
        ({"session_id": "sess-header-underscore"}, "sess-header-underscore"),
        (
            {
                "x-codex-session": "[redacted]",
                "x-codex-turn-metadata": json.dumps({"session_id": "sess-header-turn"}),
            },
            "sess-header-turn",
        ),
        (
            {"x-codex-turn-metadata": json.dumps({"session_id": "sess-header-turn"})},
            "sess-header-turn",
        ),
    ],
)
def test_codex_session_id_from_headers_supports_current_sources(
    headers: dict[str, str],
    expected: str,
) -> None:
    assert codex_session_id_from_header_lookup(headers.get) == expected
