from typing import TYPE_CHECKING, cast

from transport_matters import exchange_recorder as recorder

if TYPE_CHECKING:
    from mitmproxy import http

pytest_plugins = ("transport_matters._exchange_recorder_http_fixtures",)


def test_tag_http_error_status_preserves_parsed_usage() -> None:
    import types

    from transport_matters.storage import ResStats

    flow = types.SimpleNamespace(
        response=types.SimpleNamespace(status_code=429),
    )
    parsed = ResStats(stop_reason="end_turn", input_tokens=10, output_tokens=5, text_chars=3)
    tagged = recorder.tag_http_error_status(parsed, cast("http.HTTPFlow", flow), b"{}")
    assert tagged is not None
    assert tagged.stop_reason == "http_429"
    assert tagged.input_tokens == 10
    assert tagged.output_tokens == 5


def test_tag_http_error_status_noop_on_success() -> None:
    import types

    from transport_matters.storage import ResStats

    flow = types.SimpleNamespace(response=types.SimpleNamespace(status_code=200))
    parsed = ResStats(stop_reason="end_turn", input_tokens=10)
    assert recorder.tag_http_error_status(parsed, cast("http.HTTPFlow", flow), b"{}") is parsed
