"""Private override store state for the Manicure pipeline."""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from manicure.overrides import Override

type OverrideScope = tuple[str, str]
type OverrideKey = tuple[str, str]

LEGACY_SCOPE_ID = "__legacy__"


def root_scope(run_id: str | None) -> OverrideScope:
    scope_run_id = run_id or LEGACY_SCOPE_ID
    return scope_run_id, scope_run_id


def normalize_scope(scope: OverrideScope | None = None) -> OverrideScope:
    if scope is None:
        return root_scope(None)
    run_id, track_id = scope
    scope_run_id = run_id or LEGACY_SCOPE_ID
    return scope_run_id, track_id or scope_run_id


class OverrideStore:
    """Session-scoped override state. Lives in the addon process."""

    def __init__(self) -> None:
        self._overrides: dict[OverrideScope, OrderedDict[OverrideKey, Override]] = {}
        self._enabled: dict[OverrideScope, bool] = {}

    @property
    def enabled(self) -> bool:
        return self.is_enabled()

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self.set_enabled(value)

    def is_enabled(self, *, scope: OverrideScope | None = None) -> bool:
        return self._enabled.get(normalize_scope(scope), True)

    def set_enabled(
        self,
        value: bool,
        *,
        scope: OverrideScope | None = None,
    ) -> None:
        normalized = normalize_scope(scope)
        if value:
            self._enabled.pop(normalized, None)
        else:
            self._enabled[normalized] = False

    def upsert(
        self,
        override: Override,
        *,
        scope: OverrideScope | None = None,
    ) -> None:
        scoped = self._scoped_overrides(scope)
        key = (override.kind, override.target)
        if override.value is None:
            scoped.pop(key, None)
        else:
            scoped[key] = override

    def remove(
        self,
        kind: str,
        target: str,
        *,
        scope: OverrideScope | None = None,
    ) -> bool:
        return self._scoped_overrides(scope).pop((kind, target), None) is not None

    def get_all(self, *, scope: OverrideScope | None = None) -> list[Override]:
        return list(self._scoped_overrides(scope).values())

    def clear(self, *, scope: OverrideScope | None = None) -> None:
        if scope is None:
            self._overrides.clear()
            self._enabled.clear()
            return
        normalized = normalize_scope(scope)
        self._overrides.pop(normalized, None)
        self._enabled.pop(normalized, None)

    def _scoped_overrides(
        self, scope: OverrideScope | None
    ) -> OrderedDict[OverrideKey, Override]:
        normalized = normalize_scope(scope)
        scoped = self._overrides.get(normalized)
        if scoped is None:
            scoped = OrderedDict()
            self._overrides[normalized] = scoped
        return scoped


_store = OverrideStore()


def get_store() -> OverrideStore:
    return _store
