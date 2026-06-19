"""Unit tests for the count_tokens wrapper."""

import json
from typing import TYPE_CHECKING, cast

import httpx

from transport_matters.counting import (
    TokenCounter,
    _cache_key,
    _strip_for_count,
    get_recent_auth,
    relevant_auth_headers,
    set_recent_auth,
)
from transport_matters.shared_proxy.binding import ProxyRunBinding

if TYPE_CHECKING:
    from pathlib import Path

    from transport_matters.storage.base import StorageBackend

# ── _strip_for_count ──────────────────────────────────────────────────


def test_strip_projects_onto_count_allowlist() -> None:
    # A Claude-Code-shaped body: allowlisted count fields plus the top-level
    # fields the count endpoint rejects with 400 ("Extra inputs are not
    # permitted") — sampling/stream AND the newer metadata/context_management/
    # output_config/service_tier that the old sampling-only denylist let through.
    payload = (
        b'{"model":"c","messages":[],"system":"s","tools":[],'
        b'"tool_choice":{"type":"auto"},"thinking":{"type":"adaptive"},'
        b'"max_tokens":1,"stream":true,"temperature":0.5,"top_p":0.9,'
        b'"top_k":40,"stop_sequences":["\\n"],"metadata":{"user_id":"u"},'
        b'"context_management":{"edits":[]},"output_config":{"effort":"high"},'
        b'"service_tier":"auto"}'
    )
    data = json.loads(_strip_for_count(payload))
    # Everything not on the count allowlist is dropped.
    for key in (
        "max_tokens",
        "stream",
        "temperature",
        "top_p",
        "top_k",
        "stop_sequences",
        "metadata",
        "context_management",
        "output_config",
        "service_tier",
    ):
        assert key not in data
    # The allowlisted count fields survive verbatim.
    assert data == {
        "model": "c",
        "messages": [],
        "system": "s",
        "tools": [],
        "tool_choice": {"type": "auto"},
        "thinking": {"type": "adaptive"},
    }


def test_strip_invalid_json_passes_through_unchanged() -> None:
    bogus = b"not json"
    assert _strip_for_count(bogus) == bogus


# ── relevant_auth_headers ────────────────────────────────────────────


def test_auth_headers_picks_known_keys() -> None:
    headers = {
        "x-api-key": "sk-x",
        "authorization": "Bearer y",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "cache-2024-07-31",
        "user-agent": "foo",
        "content-type": "application/json",
    }
    result = relevant_auth_headers(headers)
    assert result == {
        "x-api-key": "sk-x",
        "authorization": "Bearer y",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "cache-2024-07-31",
    }


def test_auth_headers_skips_empty_values() -> None:
    assert relevant_auth_headers({"x-api-key": ""}) == {}


def test_auth_headers_ignores_unrelated_headers() -> None:
    assert relevant_auth_headers({"cookie": "session=1"}) == {}


# ── recent auth cache ────────────────────────────────────────────────


def _auth_binding(tmp_path: Path) -> ProxyRunBinding:
    return ProxyRunBinding(
        run_id="run-auth",
        harness="claude",
        working_dir=None,
        storage=cast("StorageBackend", object()),
        listen_port=9191,
        upstream=None,
        agent_home_dir=None,
        owned_native_session_id=None,
        owned_source_descriptor=None,
    )


def test_empty_recent_auth_clear_without_binding_clears_global() -> None:
    try:
        set_recent_auth({"x-api-key": "global-key"})
        assert get_recent_auth() == {"x-api-key": "global-key"}

        set_recent_auth({})

        assert get_recent_auth() is None
    finally:
        set_recent_auth(None)


def test_empty_recent_auth_clear_with_binding_clears_holder_and_global(
    tmp_path: Path,
) -> None:
    binding = _auth_binding(tmp_path)
    try:
        set_recent_auth({"x-api-key": "global-key"})
        set_recent_auth({"x-api-key": "binding-key"}, binding=binding)
        assert get_recent_auth() == {"x-api-key": "binding-key"}

        set_recent_auth({}, binding=binding)

        assert get_recent_auth(binding=binding) is None
        assert get_recent_auth() is None
    finally:
        set_recent_auth(None)


# ── _cache_key ────────────────────────────────────────────────────────


def test_cache_key_distinguishes_different_auth() -> None:
    payload = b'{"model":"c"}'
    assert _cache_key(payload, {"x-api-key": "a"}) != _cache_key(payload, {"x-api-key": "b"})


def test_cache_key_stable_across_dict_insertion_order() -> None:
    payload = b'{"model":"c"}'
    k1 = _cache_key(payload, {"x-api-key": "a", "authorization": "b"})
    k2 = _cache_key(payload, {"authorization": "b", "x-api-key": "a"})
    assert k1 == k2


def test_cache_key_distinguishes_different_payloads() -> None:
    auth = {"x-api-key": "a"}
    assert _cache_key(b"{}", auth) != _cache_key(b'{"x":1}', auth)


# ── TokenCounter ──────────────────────────────────────────────────────


def _client_with_handler(
    handler: object,  # httpx.MockTransport's handler type is untyped
) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return httpx.AsyncClient(
        base_url="https://api.anthropic.com",
        transport=transport,
    )


class TestTokenCounterSuccessPaths:
    async def test_200_returns_input_tokens(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"input_tokens": 42})

        async with _client_with_handler(handler) as c:
            counter = TokenCounter(c)
            result = await counter.count(
                b'{"model":"claude","messages":[]}',
                {"x-api-key": "sk-x"},
            )
        assert result == 42

    async def test_cache_skips_second_http_call(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json={"input_tokens": 7})

        async with _client_with_handler(handler) as c:
            counter = TokenCounter(c)
            a = await counter.count(b'{"model":"x"}', {"x-api-key": "a"})
            b = await counter.count(b'{"model":"x"}', {"x-api-key": "a"})
        assert a == 7
        assert b == 7
        assert calls == 1

    async def test_forwards_auth_headers_to_anthropic(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(dict(request.headers))
            return httpx.Response(200, json={"input_tokens": 1})

        async with _client_with_handler(handler) as c:
            counter = TokenCounter(c)
            await counter.count(
                b'{"model":"x"}',
                {"x-api-key": "sk-secret", "anthropic-version": "2023-06-01"},
            )
        assert seen.get("x-api-key") == "sk-secret"
        assert seen.get("anthropic-version") == "2023-06-01"

    async def test_strips_non_count_fields_from_posted_body(self) -> None:
        body: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            body.update(json.loads(request.content))
            return httpx.Response(200, json={"input_tokens": 1})

        async with _client_with_handler(handler) as c:
            counter = TokenCounter(c)
            await counter.count(
                b'{"model":"x","messages":[],"max_tokens":99,"stream":true,'
                b'"metadata":{"user_id":"u"},"context_management":{"edits":[]}}',
                {},
            )
        # The count endpoint 400s on these; the allowlist must drop them all.
        for key in ("max_tokens", "stream", "metadata", "context_management"):
            assert key not in body
        assert body.get("model") == "x"


class TestTokenCounterFailurePaths:
    async def test_429_returns_none(self) -> None:
        async with _client_with_handler(
            lambda r: httpx.Response(429, json={"error": "rate limit"})
        ) as c:
            counter = TokenCounter(c)
            assert await counter.count(b'{"model":"x"}', {}) is None

    async def test_5xx_returns_none(self) -> None:
        async with _client_with_handler(lambda r: httpx.Response(503, text="bad gateway")) as c:
            counter = TokenCounter(c)
            assert await counter.count(b'{"model":"x"}', {}) is None

    async def test_4xx_non_429_returns_none(self) -> None:
        async with _client_with_handler(lambda r: httpx.Response(400, text="bad request")) as c:
            counter = TokenCounter(c)
            assert await counter.count(b'{"model":"x"}', {}) is None

    async def test_network_error_returns_none(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        async with _client_with_handler(handler) as c:
            counter = TokenCounter(c)
            assert await counter.count(b'{"model":"x"}', {}) is None

    async def test_malformed_response_body_returns_none(self) -> None:
        async with _client_with_handler(lambda r: httpx.Response(200, content=b"not json")) as c:
            counter = TokenCounter(c)
            assert await counter.count(b'{"model":"x"}', {}) is None

    async def test_missing_input_tokens_key_returns_none(self) -> None:
        async with _client_with_handler(lambda r: httpx.Response(200, json={})) as c:
            counter = TokenCounter(c)
            assert await counter.count(b'{"model":"x"}', {}) is None

    async def test_non_int_input_tokens_returns_none(self) -> None:
        async with _client_with_handler(
            lambda r: httpx.Response(200, json={"input_tokens": "forty"})
        ) as c:
            counter = TokenCounter(c)
            assert await counter.count(b'{"model":"x"}', {}) is None


class TestTokenCounterCacheBounds:
    async def test_eviction_keeps_most_recent(self) -> None:
        async with _client_with_handler(
            lambda r: httpx.Response(200, json={"input_tokens": 1})
        ) as c:
            counter = TokenCounter(c, max_cache=2)
            await counter.count(b'{"model":"a"}', {})
            await counter.count(b'{"model":"b"}', {})
            await counter.count(b'{"model":"c"}', {})
        # The oldest entry should have been evicted; cache sits at max_cache.
        assert len(counter._cache) == 2

    async def test_failed_call_does_not_cache(self) -> None:
        state = {"phase": "fail"}

        def handler(request: httpx.Request) -> httpx.Response:
            if state["phase"] == "fail":
                return httpx.Response(503)
            return httpx.Response(200, json={"input_tokens": 5})

        async with _client_with_handler(handler) as c:
            counter = TokenCounter(c)
            assert await counter.count(b'{"model":"x"}', {}) is None
            # Flip to success; same key must retry, not serve the negative.
            state["phase"] = "ok"
            assert await counter.count(b'{"model":"x"}', {}) == 5
