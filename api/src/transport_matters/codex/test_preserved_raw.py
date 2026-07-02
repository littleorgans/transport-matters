"""Unit tests for preserved raw input item reconciliation."""

import pytest

from transport_matters.codex.preserved_raw import (
    SerializedInputItem,
    apply_preserved_input_items,
    materialize_input_items,
)


def _user_entry(index: int, text: str) -> dict[str, object]:
    return {
        "index": index,
        "raw": {
            "type": "message",
            "role": "user",
            "meta": {"turn_id": f"turn-{index}"},
            "content": [{"type": "input_text", "text": text}],
        },
    }


def _user_item(text: str, wire_index: int | None = None) -> SerializedInputItem:
    return SerializedInputItem(
        kind="message:user",
        payload={"role": "user", "content": [{"type": "input_text", "text": text}]},
        wire_index=wire_index,
    )


def test_stamped_reconcile_drops_deleted_entries() -> None:
    items = [_user_item("first", wire_index=0)]
    preserved = [_user_entry(0, "first"), _user_entry(1, "second")]

    apply_preserved_input_items(items, preserved, stamped=True)

    assert items[0].original_index == 0
    assert items[0].payload["meta"] == {"turn_id": "turn-0"}


def test_stamped_reconcile_pairs_survivor_with_its_own_entry() -> None:
    items = [_user_item("second", wire_index=1)]
    preserved = [_user_entry(0, "first"), _user_entry(1, "second")]

    apply_preserved_input_items(items, preserved, stamped=True)

    assert items[0].original_index == 1
    assert items[0].payload["meta"] == {"turn_id": "turn-1"}


def test_stamped_reconcile_falls_back_to_kind_matching_for_unstamped_items() -> None:
    # An edit that rebuilds a Message wholesale loses the stamp; the item
    # still claims a remaining entry of its kind.
    items = [_user_item("first", wire_index=0), _user_item("rebuilt")]
    preserved = [_user_entry(0, "first"), _user_entry(1, "second")]

    apply_preserved_input_items(items, preserved, stamped=True)

    assert items[1].original_index == 1
    assert items[1].payload["meta"] == {"turn_id": "turn-1"}


def test_stamped_reconcile_ignores_duplicate_stamps() -> None:
    items = [_user_item("first", wire_index=0), _user_item("copy", wire_index=0)]
    preserved = [_user_entry(0, "first")]

    apply_preserved_input_items(items, preserved, stamped=True)

    assert items[0].original_index == 0
    assert items[1].original_index is None
    assert "meta" not in items[1].payload


def test_unstamped_reconcile_raises_on_leftover_entry() -> None:
    items = [_user_item("first")]
    preserved = [_user_entry(0, "first"), _user_entry(1, "second")]

    with pytest.raises(ValueError, match=r"preserved raw input item at index 1"):
        apply_preserved_input_items(items, preserved, stamped=False)


def test_materialize_allows_gaps_left_by_deletions() -> None:
    survivor = _user_item("second", wire_index=2)
    survivor.original_index = 2

    assert materialize_input_items([survivor], allow_gaps=True) == [survivor.payload]


def test_materialize_without_gap_tolerance_raises() -> None:
    survivor = _user_item("second", wire_index=2)
    survivor.original_index = 2

    with pytest.raises(ValueError, match=r"could not materialize input ordering"):
        materialize_input_items([survivor])
