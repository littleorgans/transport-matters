"""The transcript adapter port (§4): the ABC + the frozen dataclasses every harness maps onto.

Adapters are the transcript-side anti-corruption layer. They import **only** ``ir`` (and stdlib)
so a transcript ``text``/``tool_use``/``tool_result``/``thinking``/``image`` is the *same*
``ir.ContentBlock`` the wire side emits, which is what makes ``identity_canonical`` (§3.3) hash
identical content identically across both streams (the cross-stream dedup linchpin, §4.1.3).

``SessionBinding`` is the **single canonical** session contract: slices 1/2 staged a copy in
``index/sessions.py``; this is now the one definition (DRY). It maps 1:1 to the §3 ``session``
row. ``session_id`` is already RESOLVED by the binder (claude/anthropic use the native id
directly, no proxy mint yet; codex synthesizes), so there is no separate resolve step.
"""

from abc import ABC, abstractmethod
from typing import Annotated, Any, ClassVar, Literal  # Any: native records are provider JSON

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from transport_matters.ir import ContentBlock
from transport_matters.space.models import SpaceId, WorktreeId

RawRecord = dict[str, Any]  # Any: one parsed native transcript record (jsonl line / db-row JSON)


class SessionBinding(BaseModel):
    """The resolved session_id and how it was derived. Maps 1:1 to the §3 ``session`` row."""

    model_config = ConfigDict(frozen=True)

    session_id: str  # universal correlation key (§2); session PK (resolved by the binder)
    provider: str  # wire family: anthropic | codex | gemini | opencode
    run_id: str
    cwd: str
    workspace_slug: str
    workspace_hash: str
    space_id: SpaceId | None = None
    worktree_id: WorktreeId | None = None
    started_at: str  # ISO-8601
    harness: str | None = (
        None  # harness: claude | codex | ...; nullable until the launcher plumbs it
    )
    native_session_id: str | None = None  # provider native id (for the §3.4 partial-unique guard)
    minted: bool = False  # True = we minted via --session-id (deferred); False = native / read-back
    source_descriptor: str | None = (
        None  # JSON locating the transcript source (set in §7.3, slice 4b)
    )
    template_provenance: dict[str, Any] | None = None
    parent_session_id: str | None = None
    forked_at_seq: int | None = None
    title: str | None = None
    home_dir: str | None = (
        None  # managed --agent-home-dir for this run; threaded from RunFacts so ``locate`` resolves the
        # transcript root under the managed home (§5.2c external-adoption). Survives the re-bind via
        # ``RunContext`` like ``cwd`` (set on the binding by ``bind``); ``None`` = the harness native home.
    )


class FileTailSource(BaseModel):
    """Line-addressable transcript on disk (claude/codex/gemini). Live-tail = file-watch + offset (§9)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["file_tail"] = "file_tail"
    path: str  # absolute jsonl path recorded as the event source path
    format: str  # claude_jsonl | codex_rollout | gemini_session | gemini_checkpoint
    encoding: str = "utf-8"
    home_dir: str | None = (
        None  # managed --agent-home-dir the path resolves under; None = the harness native home (§11.1).
        # Carried EXPLICITLY (not just baked into ``path``) so a §10.5 rebuild re-resolves the
        # transcript root without the live launch env. Optional + JSON-encoded → an old descriptor
        # without the field decodes to None (no ADAPTERS_VERSION bump; ``source_descriptor`` is TEXT).
    )


class PullSource(BaseModel):
    """Non-line-addressable transcript pulled via API/export/db (opencode). Live-tail = poll (§9)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["pull"] = "pull"
    ref: str  # session ref, such as an opencode ses_ id, recorded as the event source
    mechanism: str  # opencode_export | opencode_db
    command: list[str] | None = (
        None  # e.g. ["opencode", "export", "<ses_id>"]; None for direct db read
    )


TranscriptSource = Annotated[FileTailSource | PullSource, Field(discriminator="kind")]

# One codec for ``SessionBinding.source_descriptor``: the launcher encodes the owned source it
# minted (§5.2b managed-mint) and the tailer decodes it back to the discriminated TranscriptSource
# One definition keeps the on-wire descriptor shape DRY across the launch and read-back sides.
_SOURCE_ADAPTER: TypeAdapter[FileTailSource | PullSource] = TypeAdapter(TranscriptSource)


def encode_source_descriptor(source: TranscriptSource) -> str:
    """Serialize a ``TranscriptSource`` to the ``SessionBinding.source_descriptor`` JSON string."""
    return _SOURCE_ADAPTER.dump_json(source).decode("utf-8")


def decode_source_descriptor(descriptor: str) -> TranscriptSource:
    """Parse a ``source_descriptor`` JSON string back to its ``TranscriptSource`` (by ``kind``)."""
    return _SOURCE_ADAPTER.validate_json(descriptor)


class RunContext(BaseModel):
    """Input to ``bind()``: per-run facts the adapter needs."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    cwd: str
    workspace_slug: str
    workspace_hash: str
    harness: str
    started_at: str
    native_session_id: str | None = None  # read-back input: native id learned from the wire / db
    home_dir: str | None = (
        None  # managed --agent-home-dir; ``bind`` carries it onto the binding (like ``cwd``) so ``locate``
        # resolves the transcript root under the managed home. ``None`` = the harness native home.
    )


class TurnContext(BaseModel):
    """Input to ``normalize()``: the bound session + this record's position. Keeps normalize pure."""

    model_config = ConfigDict(frozen=True)

    binding: SessionBinding
    source_path: str
    seq: int  # caller-assigned positional order within session
    source_line: int | None = None  # line offset for file_tail; None for pull
    parent_id: str | None = (
        None  # previous emitted turn_id, when the format has no native parent link
    )
    parent_seq: int | None = None  # seq for parent_id, when parent_id is known
    model: str | None = None  # threaded model when not on the record
    pending_calls: dict[str, str] | None = (
        None  # iterator-maintained cross-record tool pairing (§5.3)
    )


class NormalizedTurn(BaseModel):
    """One harness turn normalized into a session event; ``parts`` carry content blocks."""

    model_config = ConfigDict(frozen=True)

    turn_id: str  # PK: native id, or uuid5(SESSION_NS, f"{session_id}|{seq}")
    session_id: str  # NOT NULL (a turn only exists under a bound session)
    run_id: str
    provider: str
    harness: str
    role: str  # user | assistant | system | tool
    seq: int
    is_sidechain: bool
    parent_id: str | None = None  # DAG parent (claude parentUuid); None at root
    ts: str | None = None  # per-turn ISO-8601 where available
    model: str | None = None
    source_path: str = ""  # tier-1 transcript source
    source_line: int | None = None  # line offset where line-addressable
    parts: list[ContentBlock] = Field(default_factory=list)  # ir union; each part → block + edge


class TranscriptAdapter(ABC):
    """Transcript-side anti-corruption layer. One concrete subclass per harness (§5), registered by ``harness``."""

    provider: ClassVar[str]
    harness: ClassVar[str]

    @abstractmethod
    async def bind(self, run: RunContext) -> SessionBinding:
        """Establish the session_id (the correlation key). claude: native id used directly,
        minted=False (no proxy --session-id mint yet); codex: read-back synth (§3.4)."""

    async def locate(self, binding: SessionBinding) -> TranscriptSource | None:
        """Read-back discovery: resolve where the transcript lives from the binding alone.

        Used by adapters whose path is derivable at registration (claude's deterministic
        ``~/.claude`` path, §5.1). Managed-mint adapters (codex §5.2b) instead OWN the path: the
        launcher stamps ``source_descriptor`` onto the binding, so they never discover and do not
        override this. The default returns ``None``: a binding with neither a ``source_descriptor``
        nor a ``locate`` override registers no cursor and stays pending (§15 risk 2)."""
        return None

    @abstractmethod
    def normalize(self, record: RawRecord, ctx: TurnContext) -> NormalizedTurn | None:
        """Pure: map ONE native record to a turn, or None to skip a non-conversational record.
        Prefer native fields (id, parentUuid, role, ts); fall back to ctx (seq, parent_id, model)."""

    def model_hint(self, record: RawRecord) -> str | None:
        """A model name carried by a NON-turn record (e.g. codex's ``turn_context``) that
        ``normalize`` skips. The tailer threads it forward onto subsequent turns via ``ctx.model``.
        Default: ``None``. Formats that carry the model on each turn record (claude) need no hint."""
        return None
