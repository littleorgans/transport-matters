"""Codex provider integration package.

Keep the package surface lightweight so low-level imports such as
``transport_matters.codex.events`` do not trigger adapter registration imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .adapter import CodexAdapter

__all__ = ["CodexAdapter"]


def __getattr__(name: str) -> Any:
    """Resolve heavyweight exports lazily to avoid package import cycles."""
    if name == "CodexAdapter":
        from .adapter import CodexAdapter

        return CodexAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
