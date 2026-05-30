"""Tests for override state management."""

from __future__ import annotations

import pytest

from transport_matters.override_state import LEGACY_SCOPE_ID, scope_from_params
from transport_matters.overrides import Override, OverrideStore, get_store


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    store = get_store()
    store.clear()
    store.enabled = True


class TestScopeFromParams:
    @pytest.mark.parametrize(
        ("run_id", "track_id", "expected"),
        [
            (None, None, (LEGACY_SCOPE_ID, LEGACY_SCOPE_ID)),
            (None, "agent-1", (LEGACY_SCOPE_ID, "agent-1")),
            ("run-1", None, ("run-1", "run-1")),
            ("run-1", "agent-1", ("run-1", "agent-1")),
            ("", "", (LEGACY_SCOPE_ID, LEGACY_SCOPE_ID)),
            ("run-1", "", ("run-1", "run-1")),
        ],
    )
    def test_legacy_and_track_fallbacks(
        self,
        run_id: str | None,
        track_id: str | None,
        expected: tuple[str, str],
    ) -> None:
        assert scope_from_params(run_id, track_id) == expected


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

    def test_scopes_are_isolated(self) -> None:
        store = OverrideStore()
        root_override = Override(kind="tool_toggle", target="tool:bash", value=False)
        sub_override = Override(kind="tool_toggle", target="tool:bash", value=True)

        store.upsert(root_override, scope=("run-1", "run-1"))
        store.upsert(sub_override, scope=("run-1", "agent-1"))

        assert store.get_all(scope=("run-1", "run-1")) == [root_override]
        assert store.get_all(scope=("run-1", "agent-1")) == [sub_override]

    def test_enabled_is_scoped(self) -> None:
        store = OverrideStore()

        store.set_enabled(False, scope=("run-1", "agent-1"))

        assert store.is_enabled(scope=("run-1", "agent-1")) is False
        assert store.is_enabled(scope=("run-1", "agent-2")) is True

    def test_module_singleton(self) -> None:
        assert get_store() is get_store()
