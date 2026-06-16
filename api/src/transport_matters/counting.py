"""Authoritative token counting via Anthropic's /v1/messages/count_tokens.

The endpoint is free and tier-rate-limited, and it is the only reliable
way to know how many tokens a given /v1/messages payload will cost.
Transport Matters uses it to replace the old chars/4 guess for pipeline
compression figures and breakpoint previews with a real answer from the same
tokenizer the model itself uses.

Failures (network, rate limit, malformed response, schema drift) degrade
to None so the UI can render an em dash instead of crashing the flow.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Protocol  # Any: raw JSON dicts, untyped header maps

import httpx

if TYPE_CHECKING:
    from transport_matters.shared_proxy.binding import ProxyRunBinding

logger = logging.getLogger(__name__)

# Headers Anthropic requires to identify the caller. authorization covers
# OAuth-style bearer tokens; x-api-key covers direct keys; the two version
# headers gate feature flags that can change the token accounting (for
# example the extended-cache beta). Other headers (user-agent, content-*)
# are either forbidden on the count endpoint or irrelevant to the count.
_AUTH_HEADER_KEYS = frozenset(
    {
        "x-api-key",
        "authorization",
        "anthropic-version",
        "anthropic-beta",
    }
)

# Fields /v1/messages/count_tokens ignores. Keeping them in the posted
# body is harmless but inflates the cache key, so two requests that only
# differ in max_tokens would miss the cache. Strip before hashing.
_STRIP_KEYS = frozenset(
    {
        "max_tokens",
        "stream",
        "temperature",
        "top_p",
        "top_k",
        "stop_sequences",
    }
)

# Path on api.anthropic.com. The client is constructed with a base_url
# pointing at the public API, so posts use just the path.
_COUNT_PATH = "/v1/messages/count_tokens"


class TokenCountingClient(Protocol):
    """Shape-only contract used by the addon's pipeline stage.

    ``TokenCounter`` is the production implementation; tests substitute a
    trivial fake that yields deterministic values.
    """

    async def count(self, payload: bytes, auth_headers: dict[str, str]) -> int | None: ...


async def count_before_after(
    counter: TokenCountingClient,
    auth: dict[str, str],
    before_payload: bytes,
    after_payload: bytes | None,
) -> tuple[int | None, int | None]:
    """Count two versions of a request, collapsing to one call when possible.

    Both the live addon stamp (``addon.stamp_pipeline_tokens``) and the
    lazy recount endpoint (``api.v1.exchanges.get_pipeline_tokens``)
    face the same decision: if the pipeline produced no structural
    change, the before and after payloads are byte-identical and a
    single count covers both sides; otherwise the two sides run
    concurrently.

    ``after_payload=None`` models "no curated IR on disk" — the
    persistence layer omits it whenever ``curated_ir == original_ir``,
    so the caller can pass None directly without re-serializing. A
    non-None but byte-equal payload still collapses to one call.

    Partial None returns reach the caller verbatim. Whether to persist
    a partial stamp (addon: no; endpoint: no) is a site-specific
    decision kept at each call site.
    """
    if after_payload is None or before_payload == after_payload:
        count = await counter.count(before_payload, auth)
        return count, count
    tokens_before, tokens_after = await asyncio.gather(
        counter.count(before_payload, auth),
        counter.count(after_payload, auth),
    )
    return tokens_before, tokens_after


def relevant_auth_headers(headers: Any) -> dict[str, str]:
    """Filter a mitmproxy/httpx headers mapping to the Anthropic auth keys.

    Accepts anything with a case-insensitive ``.get(key)`` — mitmproxy's
    Headers and a plain dict both qualify.
    """
    result: dict[str, str] = {}
    for key in _AUTH_HEADER_KEYS:
        value = headers.get(key)
        if value:
            result[key] = value
    return result


def _strip_for_count(payload: bytes) -> bytes:
    """Remove sampling and stream fields before posting to count_tokens.

    count_tokens silently discards them, but leaving them in the cache key
    would churn the cache on payloads that differ only in, e.g., the
    max_tokens the caller happened to pick.
    """
    try:
        data: dict[str, Any] = json.loads(payload)  # Any: raw JSON
    except json.JSONDecodeError:
        return payload
    stripped = {k: v for k, v in data.items() if k not in _STRIP_KEYS}
    return json.dumps(stripped, separators=(",", ":"), sort_keys=True).encode()


def _cache_key(payload: bytes, auth: dict[str, str]) -> str:
    """SHA-256 over the posted bytes and the authenticating identity.

    Auth is folded in so a cached count for account A never leaks into a
    request from account B — same payload can still cost the same number
    of tokens, but we would not know that without asking, and conflating
    identities is a surprise we do not need.
    """
    h = hashlib.sha256()
    for key in sorted(auth):
        h.update(key.encode())
        h.update(b"=")
        h.update(auth[key].encode())
        h.update(b"\0")
    h.update(b"|")
    h.update(payload)
    return h.hexdigest()


# Module-level singleton so FastAPI routes can reach the same counter
# the mitmproxy addon owns. The addon publishes via set_counter() during
# load() and clears it at done(); the re-audit route reads via get_counter()
# and gracefully returns None if the addon has not initialized yet.
_counter: TokenCounter | None = None

# Fallback cache for legacy callers. Addon flow handlers store auth on the
# current ProxyRunBinding, then expose that binding to embedded routes through
# _recent_auth_binding while Slice 1 still has one binding per process.
_recent_auth: dict[str, str] | None = None
_recent_auth_binding: ProxyRunBinding | None = None


def set_counter(counter: TokenCounter | None) -> None:
    """Register (or clear) the process-wide counter for route access."""
    global _counter
    _counter = counter


def get_counter() -> TokenCounter | None:
    """Return the process-wide counter, or None before/after the addon."""
    return _counter


def _clear_recent_auth() -> None:
    """Clear both recent auth cache holders."""
    global _recent_auth, _recent_auth_binding
    _recent_auth = None
    _recent_auth_binding = None


def set_recent_auth(
    auth: dict[str, str] | None,
    *,
    binding: ProxyRunBinding | None = None,
) -> None:
    """Cache the latest Anthropic auth headers for lazy count_tokens calls.

    Callers should pass the ``relevant_auth_headers`` filtered view, not
    raw HTTP headers, so we never keep more than the four keys the count
    endpoint accepts. Pass ``None`` or an empty mapping to clear (e.g. at
    addon shutdown).
    """
    global _recent_auth, _recent_auth_binding
    if binding is not None:
        binding.recent_auth.set(auth)
        if not auth:
            _clear_recent_auth()
            return
        _recent_auth_binding = binding
        return
    if not auth:
        _clear_recent_auth()
        return
    _recent_auth = dict(auth)


def get_recent_auth(*, binding: ProxyRunBinding | None = None) -> dict[str, str] | None:
    """Return the cached auth headers, or None if no flow has been seen."""
    source = binding or _recent_auth_binding
    if source is not None:
        return source.recent_auth.get()
    return _recent_auth


class TokenCounter:
    """LRU-cached wrapper around POST /v1/messages/count_tokens.

    The cache is bounded to keep the addon's memory flat over a long
    session. Eviction is strict FIFO on the OrderedDict (``popitem(last=False)``),
    which is equivalent to classic LRU because we ``move_to_end`` on hits.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        max_cache: int = 256,
    ) -> None:
        self._client = client
        self._max_cache = max_cache
        self._cache: OrderedDict[str, int] = OrderedDict()

    async def count(self, payload: bytes, auth_headers: dict[str, str]) -> int | None:
        """Return Anthropic's token count for the payload, or None on failure."""
        stripped = _strip_for_count(payload)
        key = _cache_key(stripped, auth_headers)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        try:
            response = await self._client.post(
                _COUNT_PATH,
                content=stripped,
                headers={**auth_headers, "content-type": "application/json"},
            )
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            logger.debug("count_tokens network error: %s", exc)
            return None

        if response.status_code == 429:
            logger.info("count_tokens rate-limited, skipping")
            return None
        if response.status_code >= 500:
            logger.warning(
                "count_tokens %d: %s",
                response.status_code,
                response.text[:200],
            )
            return None
        if response.status_code != 200:
            logger.debug(
                "count_tokens %d: %s",
                response.status_code,
                response.text[:200],
            )
            return None

        try:
            data = response.json()
        except ValueError as exc:
            logger.warning("count_tokens JSON decode error: %s", exc)
            return None
        tokens = data.get("input_tokens")
        if not isinstance(tokens, int):
            logger.warning("count_tokens missing input_tokens: %r", data)
            return None

        self._cache[key] = tokens
        if len(self._cache) > self._max_cache:
            self._cache.popitem(last=False)
        return tokens
