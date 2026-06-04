from typing import TYPE_CHECKING, Any, cast

from transport_matters import exchange_recorder as recorder
from transport_matters._exchange_recorder_http_support import (
    _Flow,
    _make_codex_state,
    _make_response_body,
    _Response,
)

if TYPE_CHECKING:
    import pytest
    from mitmproxy import http

pytest_plugins = ("transport_matters._exchange_recorder_http_fixtures",)


async def test_codex_http_derivation_receives_request_header_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = cast("http.HTTPFlow", _Flow())
    calls: list[dict[str, Any]] = []

    def fake_derive_codex_http_turn(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(
        "transport_matters.codex.http_derivation.derive_codex_http_turn",
        fake_derive_codex_http_turn,
    )

    fresh_state = _make_codex_state()
    cast("_Flow", flow).response = _Response(_make_response_body())

    persisted = await recorder._persist_http_exchange(flow, fresh_state, None)

    assert persisted is True
    assert calls[0]["request_headers"] == fresh_state.codex_request_headers

    provisional_state = _make_codex_state()
    exchange_id = await recorder._persist_http_provisional_exchange(flow, provisional_state)
    assert exchange_id is not None
    provisional_state.provisional_exchange_id = exchange_id

    finalized = await recorder._finalize_http_provisional_exchange(flow, provisional_state, None)

    assert finalized is True
    assert calls[1]["request_headers"] == provisional_state.codex_request_headers
