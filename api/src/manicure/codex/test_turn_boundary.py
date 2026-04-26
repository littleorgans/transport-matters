"""Tests for the Codex websocket turn boundary contract."""

from __future__ import annotations

from manicure.codex.turn_boundary import (
    CODEX_INTERRUPTED_STATUS,
    codex_assistant_completed_item,
    codex_close_stop_reason,
    codex_terminal_status,
    codex_terminal_stop_reason,
    is_codex_turn_start,
)


def test_codex_turn_start_uses_client_response_create_only() -> None:
    assert is_codex_turn_start({"type": "response.create"}, from_client=True) is True
    assert is_codex_turn_start({"type": "response.create"}, from_client=False) is False
    assert is_codex_turn_start({"type": "response.cancel"}, from_client=True) is False


def test_codex_terminal_boundary_uses_server_completed_and_failed_only() -> None:
    assert (
        codex_terminal_status({"type": "response.completed"}, from_client=False)
        == "completed"
    )
    assert (
        codex_terminal_status({"type": "response.failed"}, from_client=False)
        == "failed"
    )
    assert codex_terminal_status({"type": "response.failed"}, from_client=True) is None
    assert (
        codex_terminal_status({"type": "response.output_item.done"}, from_client=False)
        is None
    )


def test_codex_terminal_stop_reason_prefers_status_metadata() -> None:
    assert (
        codex_terminal_stop_reason(
            {
                "type": "response.completed",
                "response": {"status": "completed"},
            },
            from_client=False,
        )
        == "completed"
    )
    assert (
        codex_terminal_stop_reason(
            {
                "type": "response.failed",
                "response": {"incomplete_details": {"reason": "max_output_tokens"}},
            },
            from_client=False,
        )
        == "max_output_tokens"
    )


def test_codex_assistant_rollup_uses_completed_assistant_message_items_only() -> None:
    payload = {
        "type": "response.output_item.done",
        "item": {
            "id": "msg_01",
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "done"}],
        },
    }
    assert codex_assistant_completed_item(payload) == payload["item"]
    assert (
        codex_assistant_completed_item(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "message",
                    "status": "in_progress",
                    "role": "assistant",
                },
            }
        )
        is None
    )
    assert (
        codex_assistant_completed_item(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "status": "completed",
                    "role": "assistant",
                },
            }
        )
        is None
    )
    assert (
        codex_assistant_completed_item(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "message",
                    "status": "completed",
                    "role": "user",
                },
            }
        )
        is None
    )


def test_codex_websocket_close_before_terminal_is_interrupted() -> None:
    assert CODEX_INTERRUPTED_STATUS == "interrupted"
    assert codex_close_stop_reason(1006) == "ws_close_1006"
    assert codex_close_stop_reason(1000) == "ws_closed"
    assert codex_close_stop_reason(None) == "ws_closed"
