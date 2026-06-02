"""Best-effort client version detection from request headers.

Identifies the calling client (e.g. ``claude-cli/2.1.154``) so an unparsable
request can be tagged with the version that produced its unsupported shape.
"""

from typing import Any  # Any: mitmproxy Headers / dict-like with case-insensitive get


def _header(headers: Any, name: str) -> str | None:
    """Read one header value, tolerating missing or non-string results."""
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    value = getter(name)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _name_version_token(user_agent: str | None) -> str | None:
    """Extract the leading ``name/version`` token from a User-Agent string."""
    if user_agent is None:
        return None
    token = user_agent.split()[0] if user_agent.split() else ""
    name, sep, version = token.partition("/")
    if sep and name and version:
        return token
    return None


def detect_client_version(headers: Any) -> str | None:
    """Return a ``name/version`` style client identifier, or None.

    Prefers a User-Agent ``name/version`` token (Claude Code sends e.g.
    ``claude-cli/2.1.154 (external, cli)``). Falls back to the ``x-app`` and
    ``x-stainless-package-version`` headers. Returns None when nothing
    recognizable is present.
    """
    if headers is None:
        return None
    token = _name_version_token(_header(headers, "user-agent"))
    if token is not None:
        return token
    return _header(headers, "x-app") or _header(headers, "x-stainless-package-version")
