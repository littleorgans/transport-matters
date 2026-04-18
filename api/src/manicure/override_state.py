"""Private override store state for the Manicure pipeline."""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from manicure.overrides import Override


class OverrideStore:
    """Session-scoped override state. Lives in the addon process."""

    def __init__(self) -> None:
        self._overrides: OrderedDict[tuple[str, str], Override] = OrderedDict()
        self._enabled: bool = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def upsert(self, override: Override) -> None:
        key = (override.kind, override.target)
        if override.value is None:
            self._overrides.pop(key, None)
        else:
            self._overrides[key] = override

    def remove(self, kind: str, target: str) -> bool:
        return self._overrides.pop((kind, target), None) is not None

    def get_all(self) -> list[Override]:
        return list(self._overrides.values())

    def clear(self) -> None:
        self._overrides.clear()


_store = OverrideStore()


def get_store() -> OverrideStore:
    return _store
