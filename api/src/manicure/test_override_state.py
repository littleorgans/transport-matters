"""Tests for override state management."""

from __future__ import annotations

import pytest

from manicure.overrides import Override, OverrideStore, get_store


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    store = get_store()
    store.clear()
    store.enabled = True


class TestOverrideStore:
    def test_empty_store(self) -> None:
        store = OverrideStore()
        assert store.get_all() == []
        assert store.enabled is True

    def test_upsert_creates(self) -> None:
        store = OverrideStore()
        override = Override(kind="tool_toggle", target="tool:bash", value=False)
        store.upsert(override)
        assert store.get_all() == [override]

    def test_upsert_replaces(self) -> None:
        store = OverrideStore()
        original = Override(kind="tool_toggle", target="tool:bash", value=False)
        replacement = Override(kind="tool_toggle", target="tool:bash", value=True)
        store.upsert(original)
        store.upsert(replacement)
        assert len(store.get_all()) == 1
        assert store.get_all()[0].value is True

    def test_upsert_none_removes(self) -> None:
        store = OverrideStore()
        store.upsert(Override(kind="tool_toggle", target="tool:bash", value=False))
        store.upsert(Override(kind="tool_toggle", target="tool:bash", value=None))
        assert store.get_all() == []

    def test_upsert_none_missing_is_noop(self) -> None:
        store = OverrideStore()
        store.upsert(Override(kind="tool_toggle", target="tool:bash", value=None))
        assert store.get_all() == []

    def test_remove(self) -> None:
        store = OverrideStore()
        store.upsert(Override(kind="tool_toggle", target="tool:bash", value=False))
        assert store.remove("tool_toggle", "tool:bash") is True
        assert store.get_all() == []

    def test_remove_missing_returns_false(self) -> None:
        store = OverrideStore()
        assert store.remove("tool_toggle", "tool:nonexistent") is False

    def test_clear(self) -> None:
        store = OverrideStore()
        store.upsert(Override(kind="tool_toggle", target="tool:a", value=False))
        store.upsert(Override(kind="tool_toggle", target="tool:b", value=False))
        store.clear()
        assert store.get_all() == []

    def test_enabled_toggle(self) -> None:
        store = OverrideStore()
        assert store.enabled is True
        store.enabled = False
        assert store.enabled is False
        store.enabled = True
        assert store.enabled is True

    def test_module_singleton(self) -> None:
        assert get_store() is get_store()
