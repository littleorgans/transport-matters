"""System-prompt injection for the spawned ``claude`` subprocess.

`transport-matters claude` prepends a small ``--append-system-prompt`` argument
to the claude pass-through so the model knows it's running inside
Transport Matters and which URLs to point a user at. The injection is suppressed
when:

- The user passed ``--system-prompt`` or ``--append-system-prompt`` in
  their own pass-through (we don't override an explicit choice).
- The user passed ``--no-system-prompt`` to ``transport-matters claude``.

Detection is a prefix match on each pass-through token. That covers
both ``--append-system-prompt VALUE`` (two tokens) and
``--append-system-prompt=VALUE`` (one token), without depending on
claude's exact argv parser.
"""

from __future__ import annotations

from .identity import PRODUCT_LABEL
from .net import loopback_http_url

__all__ = [
    "build_system_prompt",
    "inject_system_prompt",
    "user_supplied_system_prompt",
]


_PROMPT_FLAGS: tuple[str, ...] = ("--system-prompt", "--append-system-prompt")


def build_system_prompt(*, proxy_port: int, web_port: int) -> str:
    """Render the Transport Matters system prompt for a given port pair."""
    return (
        f"You are running inside {PRODUCT_LABEL}. "
        f"Proxy URL: {loopback_http_url(proxy_port)}. "
        f"Inspector UI: {loopback_http_url(web_port)}."
    )


def user_supplied_system_prompt(passthrough: list[str]) -> bool:
    """Return True if *passthrough* already contains a ``--system-prompt``
    or ``--append-system-prompt`` token (in either ``--flag value`` or
    ``--flag=value`` form).
    """
    for token in passthrough:
        if token in _PROMPT_FLAGS:
            return True
        for flag in _PROMPT_FLAGS:
            if token.startswith(f"{flag}="):
                return True
    return False


def inject_system_prompt(passthrough: list[str], *, proxy_port: int, web_port: int) -> list[str]:
    """Prepend ``--append-system-prompt {message}`` to *passthrough*.

    Returns a new list — the input is not mutated. Caller is responsible
    for the suppression decision (call :func:`user_supplied_system_prompt`
    or honour ``--no-system-prompt`` first).
    """
    msg = build_system_prompt(proxy_port=proxy_port, web_port=web_port)
    return ["--append-system-prompt", msg, *passthrough]
