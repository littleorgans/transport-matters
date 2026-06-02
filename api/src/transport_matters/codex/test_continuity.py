from transport_matters.codex.continuity import (
    CodexContinuityAllocator,
    allocate_codex_continuity_from_headers,
    get_codex_continuity_allocator,
)


def test_same_thread_same_turn_reuses_turn_index() -> None:
    allocator = CodexContinuityAllocator()
    first = allocator.allocate(thread_id="thread-1", turn_id="turn-1")
    retry = allocator.allocate(thread_id="thread-1", turn_id="turn-1")

    assert first.turn_index == 0
    assert retry.turn_index == 0
    assert first.continuity == "exact"
    assert retry.continuity == "exact"


def test_same_thread_new_turn_increments_turn_index() -> None:
    allocator = CodexContinuityAllocator()

    first = allocator.allocate(thread_id="thread-1", turn_id="turn-1")
    second = allocator.allocate(thread_id="thread-1", turn_id="turn-2")
    second_retry = allocator.allocate(thread_id="thread-1", turn_id="turn-2")

    assert first.turn_index == 0
    assert second.turn_index == 1
    assert second_retry.turn_index == 1


def test_different_thread_ids_maintain_independent_counters() -> None:
    allocator = CodexContinuityAllocator()

    root_first = allocator.allocate(thread_id="root-thread", turn_id="turn-1")
    child_first = allocator.allocate(thread_id="child-thread", turn_id="turn-1")
    root_second = allocator.allocate(thread_id="root-thread", turn_id="turn-2")
    child_second = allocator.allocate(thread_id="child-thread", turn_id="turn-2")

    assert root_first.turn_index == 0
    assert child_first.turn_index == 0
    assert root_second.turn_index == 1
    assert child_second.turn_index == 1


def test_missing_turn_id_advances_lossy_continuity() -> None:
    allocator = CodexContinuityAllocator()

    exact = allocator.allocate(thread_id="thread-1", turn_id="turn-1")
    lossy = allocator.allocate(thread_id="thread-1", turn_id=None)
    later_exact = allocator.allocate(thread_id="thread-1", turn_id="turn-2")

    assert exact.turn_index == 0
    assert lossy.turn_index == 1
    assert lossy.turn_id is None
    assert lossy.continuity == "lossy"
    assert later_exact.turn_index == 2


def test_header_allocation_uses_current_codex_headers() -> None:
    allocator = CodexContinuityAllocator()
    headers = {
        "session-id": "parent-session",
        "thread-id": "subagent-thread",
        "x-codex-turn-metadata": '{"turn_id":"turn-1"}',
    }

    result = allocate_codex_continuity_from_headers(allocator, headers.get)

    assert result is not None
    assert result.session_id == "parent-session"
    assert result.thread_id == "subagent-thread"
    assert result.turn_id == "turn-1"
    assert result.turn_index == 0
    assert result.continuity == "exact"


def test_header_allocation_marks_malformed_metadata_lossy() -> None:
    allocator = CodexContinuityAllocator()
    headers = {
        "thread-id": "thread-1",
        "x-codex-turn-metadata": "{not-json",
    }

    result = allocate_codex_continuity_from_headers(allocator, headers.get)

    assert result is not None
    assert result.thread_id == "thread-1"
    assert result.turn_id is None
    assert result.turn_index == 0
    assert result.continuity == "lossy"


def test_header_allocation_returns_none_without_thread_identity() -> None:
    allocator = CodexContinuityAllocator()
    headers = {
        "session-id": "session-only",
        "x-codex-turn-metadata": '{"turn_id":"turn-1"}',
    }

    assert allocate_codex_continuity_from_headers(allocator, headers.get) is None


def test_default_allocator_is_process_local_shared_state() -> None:
    allocator = get_codex_continuity_allocator()
    allocator.clear()

    first = allocator.allocate(thread_id="shared-thread", turn_id="turn-1")
    retry = get_codex_continuity_allocator().allocate(
        thread_id="shared-thread",
        turn_id="turn-1",
    )

    assert first.turn_index == 0
    assert retry.turn_index == 0

    allocator.clear()
