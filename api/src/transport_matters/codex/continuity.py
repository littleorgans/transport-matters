"""Process-local Codex turn continuity allocation."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from transport_matters.codex.session_metadata import (
    codex_session_id_from_header_lookup,
    codex_thread_id_from_header_lookup,
    codex_turn_id_from_header_lookup,
)

if TYPE_CHECKING:
    from collections.abc import Callable

CodexContinuityQuality = Literal["exact", "lossy"]


@dataclass(frozen=True, slots=True)
class CodexContinuityAllocation:
    session_id: str
    thread_id: str
    turn_id: str | None
    turn_index: int
    continuity: CodexContinuityQuality


@dataclass(slots=True)
class _CodexThreadContinuity:
    turn_indices: dict[str, int] = field(default_factory=dict)
    next_turn_index: int = 0


@dataclass(slots=True)
class CodexContinuityAllocator:
    _threads: dict[str, _CodexThreadContinuity] = field(default_factory=dict)

    def clear(self) -> None:
        self._threads.clear()

    def allocate(
        self,
        *,
        thread_id: str,
        turn_id: str | None,
        session_id: str | None = None,
    ) -> CodexContinuityAllocation:
        if not thread_id:
            msg = "thread_id must be non-empty"
            raise ValueError(msg)

        state = self._threads.setdefault(thread_id, _CodexThreadContinuity())
        resolved_session_id = session_id or thread_id
        if turn_id is None:
            return self._allocate_lossy(
                state,
                thread_id=thread_id,
                session_id=resolved_session_id,
            )

        turn_index = state.turn_indices.get(turn_id)
        if turn_index is None:
            turn_index = state.next_turn_index
            state.turn_indices[turn_id] = turn_index
            state.next_turn_index += 1

        return CodexContinuityAllocation(
            session_id=resolved_session_id,
            thread_id=thread_id,
            turn_id=turn_id,
            turn_index=turn_index,
            continuity="exact",
        )

    @staticmethod
    def _allocate_lossy(
        state: _CodexThreadContinuity,
        *,
        thread_id: str,
        session_id: str,
    ) -> CodexContinuityAllocation:
        turn_index = state.next_turn_index
        state.next_turn_index += 1
        return CodexContinuityAllocation(
            session_id=session_id,
            thread_id=thread_id,
            turn_id=None,
            turn_index=turn_index,
            continuity="lossy",
        )


def allocate_codex_continuity_from_headers(
    allocator: CodexContinuityAllocator,
    get_header: Callable[[str], object | None],
) -> CodexContinuityAllocation | None:
    thread_id = codex_thread_id_from_header_lookup(get_header)
    if thread_id is None:
        return None
    return allocator.allocate(
        session_id=codex_session_id_from_header_lookup(get_header),
        thread_id=thread_id,
        turn_id=codex_turn_id_from_header_lookup(get_header),
    )


_DEFAULT_ALLOCATOR = CodexContinuityAllocator()


def get_codex_continuity_allocator() -> CodexContinuityAllocator:
    return _DEFAULT_ALLOCATOR


__all__ = [
    "CodexContinuityAllocation",
    "CodexContinuityAllocator",
    "CodexContinuityQuality",
    "allocate_codex_continuity_from_headers",
    "get_codex_continuity_allocator",
]
