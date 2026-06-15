from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence


def turn_indices_by_seq(events: Sequence[Any], *, offset: int = 0) -> dict[int, int | None]:
    current = offset
    indices: dict[int, int | None] = {}
    for event in sorted(events, key=lambda item: item.seq):
        if event.kind == "turn" and not event.is_sidechain:
            current += 1
            indices[event.seq] = current
        else:
            indices[event.seq] = current if current > 0 else None
    return indices
