"""The codex transcript adapter (§5.2) — the first READ-BACK provider.

codex mints no proxy ``--session-id``; the native thread uuid (``session_meta.payload.id``, also
the rollout filename uuid, carried in the proxied codex frames) is learned from the wire and the
``session_id`` is SYNTHESIZED via the shared ``synth_session_id`` so the wire correlation
(``bind_exchange``) and this transcript adapter independently converge on the SAME ``session_id``
(§7.2). Parts reuse ``ir.ContentBlock`` verbatim so identical content dedups to one block across
both streams (§3.3).
"""

import json
import uuid
from typing import TYPE_CHECKING, Any  # Any: rollout records are provider-shaped JSON

from transport_matters.index.adapters.base import (
    NormalizedTurn,
    SessionBinding,
    TranscriptAdapter,
)
from transport_matters.index.sessions import SESSION_NS, synth_session_id
from transport_matters.ir import (
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UnknownBlock,
)

if TYPE_CHECKING:
    from transport_matters.index.adapters.base import (
        RawRecord,
        RunContext,
        TurnContext,
    )
    from transport_matters.ir import ContentBlock


class CodexAdapter(TranscriptAdapter):
    provider = "codex"
    cli = "codex"

    async def bind(self, run: RunContext) -> SessionBinding:
        if run.native_session_id is None:
            raise ValueError(
                "codex bind requires native_session_id (the wire-observed thread uuid)"
            )
        return SessionBinding(
            # READ-BACK: session_id is SYNTHESIZED (the same helper the wire side uses, §7.2),
            # NOT the native id directly as claude does. minted=False — the id is learned, not minted.
            session_id=synth_session_id(run.run_id, self.provider, run.native_session_id),
            provider=self.provider,
            cli=self.cli,
            run_id=run.run_id,
            cwd=run.cwd,
            workspace_slug=run.workspace_slug,
            workspace_hash=run.workspace_hash,
            started_at=run.started_at,
            native_session_id=run.native_session_id,
            minted=False,
            home_dir=run.home_dir,  # carried like cwd (codex has no ``locate``, but the binding stays honest)
        )

    # No ``locate``: codex is MANAGED-MINT (§5.2b). The launcher mints the native uuid, pre-seeds the
    # rollout, and stamps the owned ``source_descriptor`` onto any wire binding whose
    # ``metadata.session_id`` matches that uuid, so the tailer byte-tails the owned path. The old
    # read-back glob (any wire frame ⇒ TM launched it ⇒ TM owns the uuid + path) is deleted; discovery
    # is unreachable for anything TM sees. Uncorrelated codex non-conversational requests, such as
    # memory-style calls, carry no session id, bind to ``None``, and land as null exchange metadata
    # rows; handshake-failure frames are tier-1 only and create no indexed wire row. These recur several
    # times per session, not a single frame-1 phantom (§15 risk 2). The base default ``locate`` returns
    # None, so codex ids with no owned descriptor register no cursor.

    def model_hint(self, record: RawRecord) -> str | None:
        # codex's model lives on the `turn_context` record (which normalize skips); the tailer threads
        # it forward via ctx.model so each response_item turn carries the active model (§5.2).
        if record.get("type") != "turn_context":
            return None
        payload = record.get("payload")
        model = payload.get("model") if isinstance(payload, dict) else None
        return model if isinstance(model, str) else None

    def normalize(self, record: RawRecord, ctx: TurnContext) -> NormalizedTurn | None:
        # Only response_items are durable conversation items; session_meta/turn_context/event_msg
        # are skipped (the last are streaming UI events, duplicative of the response_items) (§5.2).
        if record.get("type") != "response_item":
            return None
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return None
        role, parts = _payload_to_role_and_parts(payload)
        binding = ctx.binding
        return NormalizedTurn(
            # response_item has no per-record id → derive a stable PK from session_id + ordinal (§5.2).
            turn_id=str(uuid.uuid5(SESSION_NS, f"{binding.session_id}|{ctx.seq}")),
            session_id=binding.session_id,
            run_id=binding.run_id,
            provider=binding.provider,
            cli=binding.cli or self.cli,
            role=role,
            seq=ctx.seq,
            # codex subagents are separate forked threads → within a session this is always False
            # (subagent-ness is session-grained, unlike claude's per-record flag) (§5.2).
            is_sidechain=False,
            parent_id=ctx.parent_id,  # linear prev-turn chain (the format has no native parent link)
            ts=record.get("timestamp"),
            model=ctx.model,  # threaded from turn_context (the record carries no model)
            source_path=ctx.source_path,
            source_line=ctx.source_line,
            parts=parts,
        )


def _payload_to_role_and_parts(payload: dict[str, Any]) -> tuple[str, list[ContentBlock]]:
    kind = payload.get("type")
    if kind == "message":
        role = payload.get("role", "user")
        # developer-authored items are harness/system framing → the "system" turn role (§5.2).
        return ("system" if role == "developer" else role), _message_parts(payload.get("content"))
    if kind == "function_call":
        return "assistant", [_function_call_block(payload)]
    if kind == "function_call_output":
        return "tool", [_function_call_output_block(payload)]
    if kind == "reasoning":
        return "assistant", [_reasoning_block(payload)]
    # Any other durable response_item (custom_tool_call, web_search_call, …) is captured, not
    # dropped: its raw payload rides an UnknownBlock so the DIFF/audit still see it (§5.2).
    return "assistant", [UnknownBlock(raw=payload)]


def _message_parts(content: Any) -> list[ContentBlock]:
    if not isinstance(content, list):
        return []
    parts: list[ContentBlock] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        # content elems are {type: input_text|output_text, text}; anything text-less (e.g. an
        # image part) is preserved as UnknownBlock rather than silently dropped.
        parts.append(TextBlock(text=text) if isinstance(text, str) else UnknownBlock(raw=item))
    return parts


def _function_call_block(payload: dict[str, Any]) -> ToolUseBlock:
    return ToolUseBlock(
        id=payload.get("call_id", ""),
        name=payload.get("name", ""),
        input=_loads_arguments(payload.get("arguments")),
    )


def _loads_arguments(arguments: Any) -> dict[str, Any]:
    # codex serializes function-call arguments as a JSON STRING; parse it back to the ir input dict.
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return {"_raw": arguments}
        return parsed if isinstance(parsed, dict) else {"_raw": arguments}
    return {}


def _function_call_output_block(payload: dict[str, Any]) -> ToolResultBlock:
    text, is_error = _output_text_and_error(payload.get("output"))
    return ToolResultBlock(
        tool_use_id=payload.get("call_id", ""),
        content=[TextBlock(text=text)],
        is_error=is_error,
    )


def _output_text_and_error(output: Any) -> tuple[str, bool]:
    # output is usually a JSON string (e.g. {"output": "...", "metadata": {...}}) but may be a plain
    # string; the ir tool-result content is the raw output text, is_error from a structured signal.
    if isinstance(output, str):
        text = output
        try:
            parsed: Any = json.loads(output)
        except json.JSONDecodeError:
            parsed = None
    else:
        text = json.dumps(output, ensure_ascii=False) if output is not None else ""
        parsed = output
    is_error = isinstance(parsed, dict) and (
        parsed.get("success") is False or bool(parsed.get("error"))
    )
    return text, is_error


def _reasoning_block(payload: dict[str, Any]) -> ThinkingBlock:
    encrypted = payload.get("encrypted_content")
    return ThinkingBlock(
        text=_reasoning_text(payload),
        # encrypted_content rides provider_data so it is stripped from block identity (§3.3 dedup).
        provider_data={"encrypted_content": encrypted} if encrypted is not None else None,
    )


def _reasoning_text(payload: dict[str, Any]) -> str:
    summary = payload.get("summary")
    if isinstance(summary, list):
        texts = [
            s["text"] for s in summary if isinstance(s, dict) and isinstance(s.get("text"), str)
        ]
        if texts:
            return "\n".join(texts)
    content = payload.get("content")
    return content if isinstance(content, str) else ""
