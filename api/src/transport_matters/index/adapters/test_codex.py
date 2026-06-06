"""codex adapter: normalize the golden fixture per the §5.2 read-back block table; bind/locate.

Structurally faithful to the real ``rollout-*.jsonl`` envelope (verified on real samples under
``~/.codex/sessions``); content is synthetic for repo privacy (#17). codex is READ-BACK: the
session_id is synthesized (``synth_session_id``) from the native thread uuid, so the wire side and
this transcript side converge on the SAME ``session_id`` (§7.2).
"""

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from transport_matters.index.adapters.base import (
    RunContext,
    SessionBinding,
    TurnContext,
)
from transport_matters.index.adapters.codex import CodexAdapter
from transport_matters.index.conftest import make_binding
from transport_matters.index.sessions import SESSION_NS, synth_session_id
from transport_matters.ir import (
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UnknownBlock,
)

if TYPE_CHECKING:
    from transport_matters.index.adapters.base import NormalizedTurn

_FIXTURE = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "codex_rollout.jsonl"
_NATIVE = "019e0000-0000-7000-8000-00000000c0de"  # the codex thread uuid (== rollout filename uuid)
_RUN = "run1"
_MODEL = "gpt-5-codex"
_SESSION = synth_session_id(_RUN, "codex", _NATIVE)


def _binding() -> SessionBinding:
    return make_binding(
        _SESSION, provider="codex", cli="codex", run_id=_RUN, native_session_id=_NATIVE
    )


def _normalize_fixture() -> list[NormalizedTurn | None]:
    adapter = CodexAdapter()
    binding = _binding()
    out: list[NormalizedTurn | None] = []
    for line in _FIXTURE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        # seq is the record ordinal within the session (the tailer increments per record, including
        # skipped ones), so turn_id = uuid5(SESSION_NS, f"{session_id}|{seq}") is stable per line.
        ctx = TurnContext(
            binding=binding,
            source_path=str(_FIXTURE),
            source_line=len(out),
            seq=len(out),
            model=_MODEL,
            parent_id=None,
        )
        out.append(adapter.normalize(json.loads(line), ctx))
    return out


def _turns() -> list[NormalizedTurn]:
    return [t for t in _normalize_fixture() if t is not None]


class TestNormalize:
    def test_skips_session_meta_turn_context_and_event_msg(self) -> None:
        # session_meta, turn_context, agent_message, token_count → None; the 7 response_items → turns
        assert [t is None for t in _normalize_fixture()] == [
            True,  # session_meta
            True,  # turn_context
            True,  # event_msg agent_message
            True,  # event_msg token_count
            False,  # message(user)
            False,  # message(developer)
            False,  # reasoning
            False,  # function_call
            False,  # function_call_output
            False,  # message(assistant)
            False,  # custom_tool_call (unmapped response_item → captured, not dropped)
        ]

    def test_user_message_text(self) -> None:
        user = _turns()[0]
        assert (user.role, user.parts) == ("user", [TextBlock(text="run the tests")])

    def test_developer_message_maps_to_system_role(self) -> None:
        dev = _turns()[1]
        assert dev.role == "system"
        assert dev.parts == [
            TextBlock(text="<environment_context><cwd>/w</cwd></environment_context>")
        ]

    def test_reasoning_thinking_with_encrypted_in_provider_data(self) -> None:
        reasoning = _turns()[2]
        (thinking,) = reasoning.parts
        assert isinstance(thinking, ThinkingBlock)
        assert thinking.text == "Planning the run"
        assert thinking.provider_data == {"encrypted_content": "ENC-SECRET-PAYLOAD"}

    def test_function_call_tool_use_parses_arguments(self) -> None:
        call = _turns()[3]
        (tool_use,) = call.parts
        assert isinstance(tool_use, ToolUseBlock)
        assert (tool_use.id, tool_use.name) == ("call_1", "shell")
        # arguments is a JSON STRING on the wire → json.loads into the block input (a dict)
        assert tool_use.input == {"command": ["bash", "-lc", "pytest"], "timeout_ms": 120000}

    def test_function_call_output_tool_result(self) -> None:
        out = _turns()[4]
        assert out.role == "tool"
        (result,) = out.parts
        assert isinstance(result, ToolResultBlock)
        assert result.tool_use_id == "call_1"
        assert result.is_error is False
        assert result.content == [TextBlock(text='{"output":"all green"}')]

    def test_assistant_message_text(self) -> None:
        assistant = _turns()[5]
        assert (assistant.role, assistant.parts) == ("assistant", [TextBlock(text="Tests pass.")])

    def test_unmapped_response_item_captured_as_unknown(self) -> None:
        # custom_tool_call is a durable response_item not in the §5.2 table → UnknownBlock, never dropped
        unknown_turn = _turns()[6]
        (unknown,) = unknown_turn.parts
        assert isinstance(unknown, UnknownBlock)
        assert unknown.raw["type"] == "custom_tool_call"

    def test_turn_id_is_uuid5_of_session_and_seq(self) -> None:
        user = _turns()[0]  # the user message at record ordinal seq=4
        assert user.seq == 4
        assert user.turn_id == str(uuid.uuid5(SESSION_NS, f"{_SESSION}|4"))

    def test_session_grained_is_sidechain_false(self) -> None:
        assert all(t.is_sidechain is False for t in _turns())

    def test_model_and_session_threaded(self) -> None:
        for t in _turns():
            assert t.session_id == _SESSION
            assert t.model == _MODEL
            assert (t.provider, t.cli) == ("codex", "codex")

    def test_parent_id_threaded_from_ctx(self) -> None:
        # The tailer passes the prior emitted turn_id as ctx.parent_id; normalize must carry it.
        adapter = CodexAdapter()
        ctx = TurnContext(
            binding=_binding(), source_path="p", seq=9, model=_MODEL, parent_id="prev-turn"
        )
        record = {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "ok"}],
            },
        }
        turn = adapter.normalize(record, ctx)
        assert turn is not None and turn.parent_id == "prev-turn"

    def test_only_emits_content_kinds(self) -> None:
        kinds = {p.type for t in _turns() for p in t.parts}
        assert kinds <= {"text", "tool_use", "tool_result", "thinking", "image", "unknown"}


class TestBindLocate:
    async def test_bind_read_back_synthesizes_session_id(self) -> None:
        run = RunContext(
            run_id=_RUN,
            cwd="/w",
            workspace_slug="s",
            workspace_hash="h",
            cli="codex",
            started_at="t",
            native_session_id=_NATIVE,
        )
        binding = await CodexAdapter().bind(run)
        # read-back: session_id is SYNTHESIZED (not the native id directly), minted stays False
        assert binding.session_id == _SESSION
        assert binding.session_id != _NATIVE
        assert (binding.native_session_id, binding.minted) == (_NATIVE, False)

    async def test_bind_matches_wire_side_synth(self) -> None:
        # §7.2 convergence: the same helper the wire session binding uses → identical session_id
        run = RunContext(
            run_id=_RUN,
            cwd="/w",
            workspace_slug="s",
            workspace_hash="h",
            cli="codex",
            started_at="t",
            native_session_id=_NATIVE,
        )
        binding = await CodexAdapter().bind(run)
        assert binding.session_id == synth_session_id(_RUN, "codex", _NATIVE)

    async def test_bind_requires_native_session_id(self) -> None:
        run = RunContext(
            run_id=_RUN,
            cwd="/w",
            workspace_slug="s",
            workspace_hash="h",
            cli="codex",
            started_at="t",
        )
        with pytest.raises(ValueError, match="native_session_id"):
            await CodexAdapter().bind(run)

    async def test_does_not_discover_a_source(self) -> None:
        # codex is MANAGED-MINT (§5.2b): it owns the rollout path via source_descriptor and does NOT
        # implement locate — the old ~/.codex glob is deleted. The inherited base default returns
        # None, so a binding with no owned descriptor registers no cursor (stays pending).
        assert await CodexAdapter().locate(_binding()) is None


class TestRegistry:
    def test_get_adapter_returns_codex(self) -> None:
        from transport_matters.index.adapters import get_adapter

        adapter = get_adapter("codex")
        assert isinstance(adapter, CodexAdapter)
        assert (adapter.provider, adapter.cli) == ("codex", "codex")
