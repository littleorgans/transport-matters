"""Wire ingest: map a persisted exchange to a tier-2 ``IndexJob`` and the injected sink (§7.2).

``index`` sits after ``storage`` in the DAG, so this module (and only this module, plus
``writer``) imports ``storage`` types. The sink built by ``make_index_sink`` is registered in
the storage layer via dependency inversion (``storage.exchange_sink``), so there is no
``storage → index`` import.

Tier-1 first: ``bind_exchange`` + ``build_wire_job`` are cheap and synchronous (no DB, no FS
scan — ``raw_dir`` is a pure path computation), and the sink only does a non-blocking
``writer.submit``; the actual writes happen later on the writer thread (§6.3/§7.1).
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from transport_matters.index.blocks import upsert_block
from transport_matters.index.sessions import SessionBinding, resolve_session_id, upsert_session
from transport_matters.index.writer import IndexJob
from transport_matters.storage.disk_layout import DiskStorageLayout
from transport_matters.workspace import workspace_id

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

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


def build_run_facts(
    run_id: str | None, cwd: Path | None, started_at: str, cli: str | None = None
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
    )


def bind_exchange(
    entry: IndexEntry, artifacts: ExchangeArtifacts, run_facts: RunFacts
) -> SessionBinding | None:
    """Resolve this exchange's ``SessionBinding`` (the FK-parent session), or ``None``.

    The correlation id is the wire-observed ``RequestMetadata.session_id`` — an INPUT only,
    never written to ``wire_exchange.session_id`` verbatim: it is routed through a
    ``SessionBinding`` (minted-authoritative or read-back synth, §3.4). Absent correlation id
    or run id → ``None`` (``wire_exchange.session_id`` stays NULL; a later correlation upsert
    backfills it).
    """
    correlation_id = artifacts.request_ir.metadata.session_id
    if correlation_id is None or run_facts.run_id is None:
        return None
    readback = entry.provider in _READBACK_PROVIDERS
    return SessionBinding(
        provider=entry.provider,
        run_id=run_facts.run_id,
        cwd=str(run_facts.cwd) if run_facts.cwd is not None else "",
        workspace_slug=run_facts.workspace_slug,
        workspace_hash=run_facts.workspace_hash,
        started_at=run_facts.started_at,
        cli=run_facts.cli,
        native_session_id=correlation_id if readback else None,
        minted_session_id=None if readback else correlation_id,
    )


def build_wire_job(
    entry: IndexEntry, artifacts: ExchangeArtifacts, binding: SessionBinding | None
) -> IndexJob:
    """Map a persisted exchange to a frozen wire row + ordered edges and wrap it in an IndexJob.

    Char counts are reused from ``IndexEntry.req`` (``ReqStats`` already IS the production char
    accounting — DRY, §7.2); token counts from ``ResStats``; ``raw_dir`` is a tier-1 pointer
    only. The writer applies the closure in a batch (§6.3).
    """
    session_id = resolve_session_id(binding) if binding is not None else None
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
        raw_dir=str(DiskStorageLayout().new_exchange_dir(entry.id, now=entry.ts)),
    )
    parts = _flatten_parts(artifacts)

    def apply(conn: sqlite3.Connection) -> None:
        _write_wire(conn, binding, row, parts)

    return IndexJob(kind="wire", entity_id=entry.id, run_id=row.run_id or "", apply=apply)


def make_index_sink(writer: IndexWriter, run_facts: RunFacts) -> ExchangeSink:
    """Build the post-persist sink ``load_runtime`` registers: bind → build → submit (§6.4)."""

    def sink(entry: IndexEntry, artifacts: ExchangeArtifacts) -> None:
        binding = bind_exchange(entry, artifacts, run_facts)
        writer.submit(build_wire_job(entry, artifacts, binding))

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


# seq is deliberately absent from the DO UPDATE below: it is preserved per session across
# re-ingest (§6.5), so a re-tail never renumbers an existing exchange.
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
    raw_dir            = excluded.raw_dir
"""
