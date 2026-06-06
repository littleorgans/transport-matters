"""The claude transcript adapter (§5.1).

Read-back correlation on claude's NATIVE session_id (no proxy ``--session-id`` mint exists yet,
slice-2 decision A): claude writes its own ``sessionId`` to the wire (``metadata.session_id``)
and to ``~/.claude/projects/<slug>/<sessionId>.jsonl`` — verified equal on real paired samples —
so the transcript binds on that native id used directly, ``minted=False``. Parts reuse
``ir.ContentBlock`` verbatim so identical content dedups to one block across both streams (§3.3).
"""

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any  # Any: native jsonl records are provider-shaped JSON

from transport_matters.index.adapters.base import (
    FileTailSource,
    NormalizedTurn,
    SessionBinding,
    TranscriptAdapter,
)
from transport_matters.ir import (
    ImageBlock,
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
        TranscriptSource,
        TurnContext,
    )
    from transport_matters.ir import ContentBlock

# Only conversational records become turns; everything else (system/ai-title/attachment/mode/
# file-history-snapshot/queue-operation/...) is harness metadata and is skipped (§5.1).
_CONVERSATIONAL = frozenset({"user", "assistant"})


def claude_transcript_source(
    cwd: str, session_id: str, *, projects_root: Path | None = None, home_dir: Path | None = None
) -> FileTailSource:
    """The deterministic claude transcript for a session: ``<projects_root>/<cwd-slug>/<sid>.jsonl``.

    ``cwd-slug`` is claude's on-disk projects slug: EVERY non-alphanumeric char of the cwd becomes
    ``-`` (case preserved), verified on real claude 2.1.165 (``/private/tmp/tm_slug.probe_AB9`` →
    ``-private-tmp-tm-slug-probe-AB9``). A naive ``/``→``-`` leaves dots/underscores and the tailer
    byte-tails a path claude never wrote, so the slug must match claude exactly.
    The default root is claude's native ``~/.claude/projects`` (the external-adoption ``locate``
    path); the managed launcher (§5.2c) passes the home-aware root so the owned ``source_descriptor``
    it mints lands where ``claude --session-id <sid>`` writes. One definition keeps launch + read DRY.

    ``home_dir`` is the managed ``--agent-home-dir`` (when set) recorded EXPLICITLY on the descriptor so a
    §10.5 rebuild knows the root the path resolved under without the live env; ``None`` = native home.
    It is carried alongside ``projects_root`` (which is ``<home_dir>/projects``) rather than derived
    from it, since the read-side ``locate`` only has the binding's ``home_dir``, not the projects root.
    When only ``home_dir`` is supplied (the ``locate`` path), the projects root is ``<home_dir>/projects``
    — the one read-side definition of that mapping (the launch side passes ``projects_root`` directly)."""
    if projects_root is not None:
        root = projects_root
    elif home_dir is not None:
        root = home_dir / "projects"
    else:
        root = Path.home() / ".claude" / "projects"
    slug = re.sub(r"[^a-zA-Z0-9]", "-", cwd)
    return FileTailSource(
        path=str(root / slug / f"{session_id}.jsonl"),
        format="claude_jsonl",
        home_dir=str(home_dir) if home_dir is not None else None,
    )


class ClaudeAdapter(TranscriptAdapter):
    provider = "anthropic"
    cli = "claude"

    async def bind(self, run: RunContext) -> SessionBinding:
        if run.native_session_id is None:
            raise ValueError(
                "claude bind requires native_session_id (the wire metadata.session_id)"
            )
        return SessionBinding(
            session_id=run.native_session_id,  # native id used DIRECTLY (== wire metadata.session_id)
            provider=self.provider,
            cli=self.cli,
            run_id=run.run_id,
            cwd=run.cwd,
            workspace_slug=run.workspace_slug,
            workspace_hash=run.workspace_hash,
            started_at=run.started_at,
            native_session_id=run.native_session_id,
            minted=False,
            home_dir=run.home_dir,  # carried like cwd so ``locate`` resolves under the managed home
        )

    async def locate(self, binding: SessionBinding) -> TranscriptSource:
        # External-adoption fallback (§5.2c): a claude session TM did not launch (no owned descriptor)
        # resolves to claude's deterministic path. Under a managed ``--agent-home-dir`` the binding carries
        # ``home_dir`` (threaded from RunFacts), so the path resolves under the managed projects root
        # rather than ``~/.claude`` — the real correctness gap this fixes. Managed launches never reach
        # here: their owned descriptor is decoded directly by the tailer.
        return claude_transcript_source(
            binding.cwd,
            binding.session_id,
            home_dir=Path(binding.home_dir) if binding.home_dir is not None else None,
        )

    def normalize(self, record: RawRecord, ctx: TurnContext) -> NormalizedTurn | None:
        if record.get("type") not in _CONVERSATIONAL:
            return None
        turn_id = record.get("uuid")
        if not isinstance(turn_id, str):
            return None
        message = record.get("message") or {}
        binding = ctx.binding
        return NormalizedTurn(
            turn_id=turn_id,
            session_id=binding.session_id,
            run_id=binding.run_id,
            provider=binding.provider,
            cli=binding.cli or self.cli,
            role=message.get("role", record["type"]),
            seq=ctx.seq,
            is_sidechain=bool(record.get("isSidechain", False)),
            parent_id=record.get("parentUuid"),
            ts=record.get("timestamp"),
            model=message.get("model"),
            source_path=ctx.source_path,
            source_line=ctx.source_line,
            parts=_content_to_parts(message.get("content")),
        )


def _content_to_parts(content: Any) -> list[ContentBlock]:
    if isinstance(content, str):
        return [TextBlock(text=content)]
    if isinstance(content, list):
        return [_block(item) for item in content if isinstance(item, dict)]
    return []


def _block(block: dict[str, Any]) -> ContentBlock:
    kind = block.get("type")
    if kind == "text":
        return TextBlock(text=block.get("text", ""))
    if kind == "thinking":
        signature = block.get("signature")
        return ThinkingBlock(
            text=block.get("thinking", ""),
            provider_data={"signature": signature} if signature is not None else None,
        )
    if kind == "tool_use":
        return ToolUseBlock(
            id=block.get("id", ""), name=block.get("name", ""), input=block.get("input") or {}
        )
    if kind == "tool_result":
        return ToolResultBlock(
            tool_use_id=block.get("tool_use_id", ""),
            content=_tool_result_content(block.get("content")),
            is_error=bool(block.get("is_error", False)),
        )
    if kind == "image":
        return ImageBlock(source=block.get("source") or {})
    return UnknownBlock(raw=block)


def _tool_result_content(content: Any) -> list[TextBlock | ImageBlock | UnknownBlock]:
    if isinstance(content, str):
        return [TextBlock(text=content)]
    if not isinstance(content, list):
        return []
    out: list[TextBlock | ImageBlock | UnknownBlock] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "text":
            out.append(TextBlock(text=item.get("text", "")))
        elif kind == "image":
            out.append(ImageBlock(source=item.get("source") or {}))
        else:
            out.append(UnknownBlock(raw=item))
    return out
