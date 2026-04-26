"""Fixture-backed tests for Codex transport diagnostics."""

from __future__ import annotations

import json
from pathlib import Path

from manicure.codex.diagnostics import build_codex_transport_diagnostics
from manicure.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
)
from manicure.storage.base import ExchangeArtifacts, TransportArtifacts

_FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"


def _transport_fixture(name: str) -> TransportArtifacts:
    return TransportArtifacts.model_validate_json((_FIXTURES / name).read_text())


def _response_fixture(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


def _request_ir() -> InternalRequest:
    return InternalRequest(
        model="codex/gpt-5-codex",
        provider="codex",
        system=[],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text="fixture")])],
        sampling=SamplingParams(max_tokens=0),
        metadata=RequestMetadata(),
        stream=True,
    )


def test_transport_success_fixture_stays_diagnostic_free() -> None:
    diagnostics = build_codex_transport_diagnostics(
        ExchangeArtifacts(
            request_raw=json.dumps({"type": "response.create"}).encode(),
            request_ir=_request_ir(),
            transport=_transport_fixture("codex_transport_chatgpt_success.json"),
        )
    )

    assert diagnostics == []


def test_transport_fixture_reports_chatgpt_auth_rejection() -> None:
    diagnostics = build_codex_transport_diagnostics(
        ExchangeArtifacts(
            request_raw=b"",
            request_ir=_request_ir(),
            response_raw=_response_fixture("codex_transport_chatgpt_403_response.txt"),
            transport=_transport_fixture("codex_transport_chatgpt_403.json"),
        )
    )

    assert [diagnostic.code for diagnostic in diagnostics] == ["chatgpt_auth_rejected"]
    assert diagnostics[0].severity == "error"
    assert "upgrade response status=403" in (diagnostics[0].detail or "")
    assert "response body redacted" in (diagnostics[0].detail or "")
    assert "status indicates an upstream auth challenge" in (
        diagnostics[0].detail or ""
    )
    assert "Unauthorized websocket upgrade" not in (diagnostics[0].detail or "")
    assert any("ChatGPT" in check for check in diagnostics[0].operator_checks)


def test_transport_fixture_reports_proxy_trust_failure() -> None:
    diagnostics = build_codex_transport_diagnostics(
        ExchangeArtifacts(
            request_raw=b"",
            request_ir=_request_ir(),
            response_raw=_response_fixture("codex_transport_proxy_502_response.txt"),
            transport=_transport_fixture("codex_transport_proxy_502.json"),
        )
    )

    assert [diagnostic.code for diagnostic in diagnostics] == ["proxy_trust_failed"]
    assert diagnostics[0].severity == "error"
    assert "response body redacted" in (diagnostics[0].detail or "")
    assert "UnknownIssuer" not in (diagnostics[0].detail or "")
    assert any(
        "CODEX_CA_CERTIFICATE" in check for check in diagnostics[0].operator_checks
    )


def test_transport_fixture_redacts_generic_handshake_failure_body() -> None:
    diagnostics = build_codex_transport_diagnostics(
        ExchangeArtifacts(
            request_raw=b"",
            request_ir=_request_ir(),
            response_raw=b"upstream timeout: raw-secret",
            transport=TransportArtifacts.model_validate(
                {
                    "provider": "codex",
                    "protocol": "websocket",
                    "upgrade": {
                        "scheme": "wss",
                        "host": "chatgpt.com",
                        "path": "/backend-api/codex/responses?client=cli",
                        "request_headers": [],
                        "response_status_code": 504,
                        "response_headers": [
                            {"name": "content-type", "value": "text/plain"}
                        ],
                    },
                    "close": None,
                    "messages": [],
                }
            ),
        )
    )

    assert [diagnostic.code for diagnostic in diagnostics] == [
        "websocket_handshake_failed"
    ]
    assert diagnostics[0].severity == "error"
    assert "response body redacted (28 bytes)" in (diagnostics[0].detail or "")
    assert "raw-secret" not in (diagnostics[0].detail or "")
