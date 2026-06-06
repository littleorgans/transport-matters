"""Wire ingest: map a persisted exchange to a tier-2 ``IndexJob`` and the injected sink (§7.2).

``index`` sits after ``storage`` in the DAG, so this module (and only this module, plus
``writer``) imports ``storage`` types. The sink built by ``make_index_sink`` is registered in
the storage layer via dependency inversion (``storage.exchange_sink``), so there is no
``storage → index`` import.

Tier-1 first: ``bind_exchange`` + ``build_wire_job`` are cheap and synchronous (no DB, no FS
scan, ``raw_dir`` is a pure path computation), and the sink only does a non-blocking
``writer.submit``; the actual writes happen later on the writer thread (§6.3/§7.1).
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from transport_matters.index.adapters.base import SessionBinding
from transport_matters.index.blocks import upsert_block
from transport_matters.index.sessions import synth_session_id, upsert_session
from transport_matters.index.writer import IndexJob
from transport_matters.storage.disk_layout import DiskStorageLayout
from transport_matters.workspace import workspace_id

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path

    from transport_matters.index.adapters.base import NormalizedTurn
    from transport_matters.index.blocks import IndexablePart
    from transport_matters.index.writer import IndexWriter
    from transport_matters.storage.base import ExchangeArtifacts, IndexEntry
    from transport_matters.storage.exchange_sink import ExchangeSink

# Providers whose session id is a native thread id we read back off the wire and must
# synthesize a stable PK from (§3.4). Everything else (anthropic, gemini) carries an
# authoritative session id, used directly. Refined per-provider in slices 5/6.
_READBACK_PROVIDERS = frozenset({"codex", "opencode"})


@dataclass(frozen=True, slots=True)
class RunFacts:
    """Per-run static facts captured once at ``load_runtime`` and closed over by the sink.

    They supply the ``session`` row's columns that are absent from ``IndexEntry`` /
    ``RequestMetadata`` (cwd, workspace, cli, started_at), so ``bind_exchange`` can assemble a
    full ``SessionBinding`` without a ``storage → index`` import.
    """

    run_id: str | None
    cwd: Path | None
    workspace_slug: str
    workspace_hash: str
    started_at: str
    cli: str | None = None
    # Managed ``--home-dir`` for this run (§11.1), threaded from the launch env. Stamped onto EVERY
    # binding (not just owned) so ``locate`` resolves the transcript root under the managed home for an
    # external-adoption-under-managed-home claude session. ``None`` off a non-managed / native-home run.
    home_dir: Path | None = None
    # Managed-mint (§5.2b/§5.2c): provider-neutral. The native id the launcher minted (== the
    # wire-observed session id) and the JSON ``source_descriptor`` of the transcript it owns.
    # ``bind_exchange`` stamps the descriptor onto the session whose wire id matches
    # ``owned_native_session_id``; a non-owned id matches nothing and stays pending (no cursor).
    # ``None`` off a managed launch (claude: deterministic path; codex: pre-seeded rollout).
    owned_native_session_id: str | None = None
    owned_source_descriptor: str | None = None


def build_run_facts(
    run_id: str | None,
    cwd: Path | None,
    started_at: str,
    cli: str | None = None,
    *,
    home_dir: Path | None = None,
    owned_native_session_id: str | None = None,
    owned_source_descriptor: str | None = None,
) -> RunFacts:
    """Assemble per-run static facts, deriving the workspace identity from ``cwd``."""
    slug, workspace_hash = ("", "")
    if cwd is not None:
        workspace = workspace_id(cwd)
        slug, workspace_hash = workspace.slug, workspace.hash
    return RunFacts(
        run_id=run_id,
        cwd=cwd,
        workspace_slug=slug,
        workspace_hash=workspace_hash,
        started_at=started_at,
        cli=cli,
        home_dir=home_dir,
        owned_native_session_id=owned_native_session_id,
        owned_source_descriptor=owned_source_descriptor,
    )


def bind_exchange(
    entry: IndexEntry, artifacts: ExchangeArtifacts, run_facts: RunFacts
) -> SessionBinding | None:
    """Resolve this exchange's ``SessionBinding`` (the FK-parent session), or ``None``.

    The correlation id is the wire-observed ``RequestMetadata.session_id``, an INPUT only,
    routed through the canonical ``SessionBinding`` (§4.2). anthropic/gemini use the native id
    DIRECTLY as the session_id (== claude's transcript ``sessionId``, the HARD-GATE correlation
    linchpin); read-back providers synth a stable PK (§3.4). ``native_session_id`` is always the
    raw id. Absent correlation id or run id → ``None`` (``wire_exchange.session_id`` stays NULL; a
    later correlation upsert backfills it).

    Managed-mint (§5.2b/§5.2c) is provider-neutral: when this exchange IS the session the launcher
    minted (its wire id == ``owned_native_session_id``), it carries the owned transcript descriptor
    so the session row is populated and the tailer byte-tails the owned path (no discovery). A wire id
    TM did not own matches nothing → descriptor stays ``None`` → stays pending (regression c).
    ``minted`` is ``True`` only for a direct-id provider that adopts the injected ``--session-id`` as
    its session_id used directly (claude); a read-back provider (codex) keeps its synth session_id
    (the §3.4 idempotency PK), so it owns the rollout path but stays ``minted=False``.
    """
    correlation_id = artifacts.request_ir.metadata.session_id
    if correlation_id is None or run_facts.run_id is None:
        return None
    readback = entry.provider in _READBACK_PROVIDERS
    session_id = (
        synth_session_id(run_facts.run_id, entry.provider, correlation_id)
        if readback
        else correlation_id
    )
    is_owned = (
        run_facts.owned_native_session_id is not None
        and correlation_id == run_facts.owned_native_session_id
    )
    source_descriptor = run_facts.owned_source_descriptor if is_owned else None
    return SessionBinding(
        session_id=session_id,
        provider=entry.provider,
        run_id=run_facts.run_id,
        cwd=str(run_facts.cwd) if run_facts.cwd is not None else "",
        workspace_slug=run_facts.workspace_slug,
        workspace_hash=run_facts.workspace_hash,
        started_at=run_facts.started_at,
        cli=run_facts.cli,
        native_session_id=correlation_id,
        minted=is_owned and not readback,
        source_descriptor=source_descriptor,
        # Stamped on EVERY binding (not gated on ``is_owned``): an external-adoption claude session
        # under a managed home has no owned descriptor and falls to ``locate``, which needs it (§11.1).
        home_dir=str(run_facts.home_dir) if run_facts.home_dir is not None else None,
    )


def build_wire_job(
    entry: IndexEntry,
    artifacts: ExchangeArtifacts,
    binding: SessionBinding | None,
    *,
    storage_root: Path | None = None,
) -> IndexJob:
    """Map a persisted exchange to a frozen wire row + ordered edges and wrap it in an IndexJob.

    Char counts are reused from ``IndexEntry.req`` (``ReqStats`` already IS the production char
    accounting, DRY, §7.2); token counts from ``ResStats``. ``raw_dir`` is a tier-1 pointer
    only: it MUST be rooted at the backend's actual storage root (``storage_root``), which is
    workspace-scoped (``settings.storage_dir``) at runtime. The global default root is used only
    when no root is supplied (unit callers). Reconstructing the dir from ``entry.id`` + ``entry.ts``
    is exact: the recorder persists via the same ``new_exchange_dir(id, now=entry.ts)`` policy.
    ``None`` would dangle the absolute pointer if tier-1 lives off the default root. The writer
    applies the closure in a batch (§6.3).
    """
    session_id = binding.session_id if binding is not None else None
    res = entry.res
    row = _WireRow(
        exchange_id=entry.id,
        session_id=session_id,
        run_id=entry.run_id or (binding.run_id if binding is not None else None),
        provider=entry.provider,
        model=entry.model,
        ts=entry.ts.isoformat(),
        req_system_chars=entry.req.system_chars,
        req_tools_chars=entry.req.tools_chars,
        req_messages_chars=entry.req.messages_chars,
        req_tokens=res.input_tokens if res is not None else None,
        res_tokens=res.output_tokens if res is not None else None,
        stop_reason=res.stop_reason if res is not None else None,
        mutated_manually=1 if entry.mutated_manually else 0,
        raw_dir=str(DiskStorageLayout(storage_root).new_exchange_dir(entry.id, now=entry.ts)),
    )
    parts = _flatten_parts(artifacts)

    def apply(conn: sqlite3.Connection) -> None:
        _write_wire(conn, binding, row, parts)

    return IndexJob(kind="wire", entity_id=entry.id, run_id=row.run_id or "", apply=apply)


def make_index_sink(
    writer: IndexWriter | None,
    run_facts: RunFacts,
    on_binding: Callable[[SessionBinding], None] | None = None,
    *,
    storage_root: Path | None = None,
) -> ExchangeSink:
    """Build the post-persist sink ``load_runtime`` registers: bind and optionally submit (§6.4).

    ``on_binding`` (injected by ``load_runtime``, so ingest never imports the tailer, no cycle) is
    invoked once per resolved wire binding so the transcript tailer can register that session's
    cursor read-back style, the first wire frame is what reveals the session_id (§9.2/§15 risk 2).

    ``storage_root`` is the backend's actual (workspace-scoped) storage root; it is threaded into
    ``raw_dir`` so the tier-2 pointer resolves to the tier-1 bytes the backend wrote. ``load_runtime``
    passes the ``DiskStorageBackend`` root, this is the injection point, so ``index`` never imports
    ``storage`` (the §DAG back-edge stays absent).
    """

    def sink(entry: IndexEntry, artifacts: ExchangeArtifacts) -> None:
        binding = bind_exchange(entry, artifacts, run_facts)
        if writer is not None:
            # Legacy SQLite consumers still accept the wire job before cursor registration. Live
            # runtime passes no writer in the Postgres session-store slice, so this becomes binding
            # discovery only and leaves the parked wire path unfed.
            writer.submit(build_wire_job(entry, artifacts, binding, storage_root=storage_root))
        if binding is not None and on_binding is not None:
            on_binding(binding)

    return sink


@dataclass(frozen=True, slots=True)
class _WireRow:
    exchange_id: str
    session_id: str | None
    run_id: str | None
    provider: str
    model: str
    ts: str
    req_system_chars: int
    req_tools_chars: int
    req_messages_chars: int
    req_tokens: int | None
    res_tokens: int | None
    stop_reason: str | None
    mutated_manually: int
    raw_dir: str


def _flatten_parts(artifacts: ExchangeArtifacts) -> list[tuple[str, str, IndexablePart]]:
    """Flatten request system → tools → messages → response into one ordered part stream.

    ``role`` and ``section`` live on the edge, never on the block (§3.5). System and tool_def
    blocks arise only here (the wire request regions), never from transcripts (§4.1.4).
    """
    parts: list[tuple[str, str, IndexablePart]] = []
    request = artifacts.request_ir
    for system_part in request.system:
        parts.append(("system", "system", system_part))
    for tool in request.tools:
        parts.append(("system", "tools", tool))
    for message in request.messages:
        for block in message.content:
            parts.append((message.role, "messages", block))
    response = artifacts.response_ir
    if response is not None:
        for block in response.content:
            parts.append(("assistant", "response", block))
    return parts


def _write_wire(
    conn: sqlite3.Connection,
    binding: SessionBinding | None,
    row: _WireRow,
    parts: list[tuple[str, str, IndexablePart]],
) -> None:
    """Apply one wire exchange inside the writer's per-job SAVEPOINT: session → exchange → edges.

    Idempotent (§3.7): the exchange upserts by PK, ``seq`` is preserved on re-ingest, and the
    edges are deleted then re-inserted (replace, not duplicate).
    """
    if binding is not None:
        upsert_session(conn, binding)
    seq = _next_seq(conn, row.session_id)
    conn.execute(
        _WIRE_UPSERT,
        (
            row.exchange_id,
            row.session_id,
            row.run_id,
            row.provider,
            row.model,
            row.ts,
            seq,
            row.req_system_chars,
            row.req_tools_chars,
            row.req_messages_chars,
            row.req_tokens,
            row.res_tokens,
            row.stop_reason,
            row.mutated_manually,
            row.raw_dir,
        ),
    )
    conn.execute("DELETE FROM exchange_block WHERE exchange_id = ?", (row.exchange_id,))
    for pos, (role, section, part) in enumerate(parts):
        block_id = upsert_block(conn, part)
        conn.execute(
            "INSERT INTO exchange_block (exchange_id, pos, block_id, role, section) "
            "VALUES (?, ?, ?, ?, ?)",
            (row.exchange_id, pos, block_id, role, section),
        )


def _next_seq(conn: sqlite3.Connection, session_id: str | None) -> int | None:
    """Assign ``seq = MAX(seq)+1`` within the session; NULL while uncorrelated (§6.5)."""
    if session_id is None:
        return None
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), -1) + 1 FROM wire_exchange WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return int(row[0])


# seq on conflict = COALESCE(existing, freshly-computed): an already-assigned seq is preserved
# (a re-tail never renumbers an exchange, §6.5), but an exchange first written UNcorrelated
# (seq NULL) is back-filled when a later correlation upsert supplies its session (brief :45-56).
_WIRE_UPSERT = """
INSERT INTO wire_exchange (
    exchange_id, session_id, run_id, provider, model, ts, seq,
    req_system_chars, req_tools_chars, req_messages_chars, req_tokens, res_tokens,
    stop_reason, mutated_manually, raw_dir
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(exchange_id) DO UPDATE SET
    session_id         = excluded.session_id,
    run_id             = excluded.run_id,
    provider           = excluded.provider,
    model              = excluded.model,
    ts                 = excluded.ts,
    req_system_chars   = excluded.req_system_chars,
    req_tools_chars    = excluded.req_tools_chars,
    req_messages_chars = excluded.req_messages_chars,
    req_tokens         = excluded.req_tokens,
    res_tokens         = excluded.res_tokens,
    stop_reason        = excluded.stop_reason,
    mutated_manually   = excluded.mutated_manually,
    raw_dir            = excluded.raw_dir,
    seq                = COALESCE(wire_exchange.seq, excluded.seq)
"""


def build_transcript_job(turn: NormalizedTurn, binding: SessionBinding) -> IndexJob:
    """Map a NormalizedTurn + its SessionBinding to a transcript ``IndexJob`` (§7.3).

    The binding supplies the FK-parent ``session`` row; the turn supplies everything else. ``parts``
    are ``ir.ContentBlock``s, so identical content dedups to the same ``block.hash`` as the wire
    side, which is what makes the §8.4 pivot/diff exact. The job carries the lightweight live SSE
    event (§9.4); the writer pushes it AFTER COMMIT.
    """
    event: dict[str, object] = {
        "type": "transcript_turn",
        "session_id": turn.session_id,
        "turn_id": turn.turn_id,
        "run_id": turn.run_id,
        "seq": turn.seq,
        "role": turn.role,
        "ts": turn.ts,
        "is_sidechain": turn.is_sidechain,
        "cli": turn.cli,
        "provider": turn.provider,
    }

    def apply(conn: sqlite3.Connection) -> None:
        _write_transcript(conn, binding, turn)

    return IndexJob(
        kind="transcript", entity_id=turn.turn_id, run_id=turn.run_id, apply=apply, event=event
    )


def _write_transcript(
    conn: sqlite3.Connection, binding: SessionBinding, turn: NormalizedTurn
) -> None:
    """Apply one transcript turn in its SAVEPOINT: session → transcript_turn → turn_block edges.

    Idempotent (§3.7): upsert by ``turn_id`` PK; edges deleted then re-inserted. A transcript turn
    carries ONE role, so every edge takes the turn's role (§4.3).
    """
    upsert_session(conn, binding)
    conn.execute(
        _TRANSCRIPT_UPSERT,
        (
            turn.turn_id,
            turn.session_id,
            turn.run_id,
            turn.provider,
            turn.cli,
            turn.parent_id,
            turn.role,
            turn.seq,
            turn.ts,
            1 if turn.is_sidechain else 0,
            turn.model,
            turn.source_path,
            turn.source_line,
        ),
    )
    conn.execute("DELETE FROM turn_block WHERE turn_id = ?", (turn.turn_id,))
    for pos, part in enumerate(turn.parts):
        block_id = upsert_block(conn, part)
        conn.execute(
            "INSERT INTO turn_block (turn_id, pos, block_id, role) VALUES (?, ?, ?, ?)",
            (turn.turn_id, pos, block_id, turn.role),
        )


_TRANSCRIPT_UPSERT = """
INSERT INTO transcript_turn (
    turn_id, session_id, run_id, provider, cli, parent_id, role, seq, ts, is_sidechain,
    model, source_path, source_line
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(turn_id) DO UPDATE SET
    session_id   = excluded.session_id,
    run_id       = excluded.run_id,
    provider     = excluded.provider,
    cli          = excluded.cli,
    parent_id    = excluded.parent_id,
    role         = excluded.role,
    seq          = excluded.seq,
    ts           = excluded.ts,
    is_sidechain = excluded.is_sidechain,
    model        = excluded.model,
    source_path  = excluded.source_path,
    source_line  = excluded.source_line
"""
