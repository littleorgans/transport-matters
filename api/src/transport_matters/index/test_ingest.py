"""Wire ingest: binding resolution, field mapping, ordered edges, idempotency (§13.2 + §7.1)."""

from pathlib import Path
from typing import TYPE_CHECKING, cast

from transport_matters.index.adapters.base import (
    FileTailSource,
    NormalizedTurn,
    encode_source_descriptor,
)
from transport_matters.index.conftest import make_binding
from transport_matters.index.db import connect
from transport_matters.index.ingest import (
    RunFacts,
    bind_exchange,
    build_transcript_job,
    build_wire_job,
    make_index_sink,
)
from transport_matters.index.sessions import synth_session_id
from transport_matters.index.writer import IndexJob, IndexWriter
from transport_matters.ir import Message, SystemPart, TextBlock
from transport_matters.storage.base import ReqStats, ResStats
from transport_matters.storage.disk_layout import DiskStorageLayout
from transport_matters.storage.test_exchange_support import (
    make_artifacts,
    make_index_entry,
    make_request_ir,
    make_response_ir,
)
from transport_matters.test_override_support import TOOL_BASH

if TYPE_CHECKING:
    import sqlite3


def _run_facts(
    run_id: str | None = "run1",
    *,
    cli: str | None = None,
    home_dir: Path | None = None,
    owned_native_session_id: str | None = None,
    owned_source_descriptor: str | None = None,
) -> RunFacts:
    return RunFacts(
        run_id=run_id,
        cwd=Path("/w"),
        workspace_slug="slug",
        workspace_hash="hash",
        started_at="2026-06-05T00:00:00Z",
        cli=cli,
        home_dir=home_dir,
        owned_native_session_id=owned_native_session_id,
        owned_source_descriptor=owned_source_descriptor,
    )


class TestBindExchange:
    def test_anthropic_uses_native_id_directly(self) -> None:
        entry = make_index_entry(provider="anthropic")
        artifacts = make_artifacts(make_request_ir(session_id="sess-1"))
        binding = bind_exchange(entry, artifacts, _run_facts())
        assert binding is not None
        assert binding.session_id == "sess-1"  # native id used directly (== transcript sessionId)
        assert binding.native_session_id == "sess-1"
        assert binding.minted is False

    def test_readback_provider_synthesizes(self) -> None:
        entry = make_index_entry(provider="codex")
        artifacts = make_artifacts(make_request_ir(session_id="native-9"))
        binding = bind_exchange(entry, artifacts, _run_facts())
        assert binding is not None
        assert binding.native_session_id == "native-9"
        assert binding.session_id == synth_session_id("run1", "codex", "native-9")
        assert binding.minted is False

    def test_home_dir_stamped_on_every_binding(self) -> None:
        # The managed --home-dir (§11.1) is stamped on EVERY binding (not gated on ``is_owned``): an
        # external-adoption claude session under a managed home has no owned descriptor and falls to
        # ``locate``, which needs the home on the binding to resolve the transcript root.
        entry = make_index_entry(provider="anthropic")
        artifacts = make_artifacts(make_request_ir(session_id="sess-1"))
        binding = bind_exchange(
            entry, artifacts, _run_facts(cli="claude", home_dir=Path("/managed"))
        )
        assert binding is not None
        assert binding.home_dir == "/managed"  # serialized to str on the binding

    def test_home_dir_none_off_native_run(self) -> None:
        entry = make_index_entry(provider="anthropic")
        artifacts = make_artifacts(make_request_ir(session_id="sess-1"))
        binding = bind_exchange(entry, artifacts, _run_facts())
        assert binding is not None
        assert binding.home_dir is None

    def test_no_correlation_id_returns_none(self) -> None:
        artifacts = make_artifacts(make_request_ir(session_id=None))
        assert bind_exchange(make_index_entry(), artifacts, _run_facts()) is None

    def test_no_run_id_returns_none(self) -> None:
        artifacts = make_artifacts(make_request_ir(session_id="sess-1"))
        assert bind_exchange(make_index_entry(), artifacts, _run_facts(run_id=None)) is None

    def test_owned_codex_session_stamps_descriptor_and_cli(self) -> None:
        # Managed-mint (§5.2b): the launcher minted native-9 and pre-seeded its rollout, handing the
        # addon the owned descriptor + cli via run_facts. When the wire id matches the owned uuid the
        # binding carries both, so the session row is populated (cli + source_descriptor) BEFORE any
        # transcript turn lands and the tailer byte-tails the owned path instead of globbing.
        descriptor = encode_source_descriptor(
            FileTailSource(path="/home/u/.codex/sessions/r-native-9.jsonl", format="codex_rollout")
        )
        entry = make_index_entry(provider="codex")
        artifacts = make_artifacts(make_request_ir(session_id="native-9"))
        binding = bind_exchange(
            entry,
            artifacts,
            _run_facts(
                cli="codex", owned_native_session_id="native-9", owned_source_descriptor=descriptor
            ),
        )
        assert binding is not None
        assert binding.cli == "codex"
        assert binding.source_descriptor == descriptor
        assert binding.session_id == synth_session_id("run1", "codex", "native-9")
        # codex keeps its synth session_id (§3.4 PK) — owning the id does NOT make it minted (§5.2c).
        assert binding.minted is False

    def test_owned_claude_session_is_minted_and_described(self) -> None:
        # Managed-mint (§5.2c): TM launched claude with ``--session-id <uuid>``, so claude adopts the
        # owned uuid as its session_id AND writes it to the wire. When the wire id == the owned uuid
        # the binding is minted=True (direct-id provider: the injected id IS the session_id) and
        # carries the owned deterministic transcript descriptor, so the tailer byte-tails the owned
        # path instead of ``locate``-ing it.
        descriptor = encode_source_descriptor(
            FileTailSource(
                path="/home/u/.claude/projects/-w/owned-uuid.jsonl", format="claude_jsonl"
            )
        )
        entry = make_index_entry(provider="anthropic")
        artifacts = make_artifacts(make_request_ir(session_id="owned-uuid"))
        binding = bind_exchange(
            entry,
            artifacts,
            _run_facts(
                cli="claude",
                owned_native_session_id="owned-uuid",
                owned_source_descriptor=descriptor,
            ),
        )
        assert binding is not None
        assert binding.session_id == "owned-uuid"  # native id used directly (== wire id)
        assert binding.minted is True
        assert binding.source_descriptor == descriptor
        assert binding.cli == "claude"

    def test_unowned_claude_session_is_not_minted(self) -> None:
        # External adoption (regression c): a claude wire id TM did NOT launch (no owned id) is not
        # minted and carries no descriptor — it falls back to the adapter's deterministic ``locate``.
        entry = make_index_entry(provider="anthropic")
        artifacts = make_artifacts(make_request_ir(session_id="external-uuid"))
        binding = bind_exchange(entry, artifacts, _run_facts(cli="claude"))
        assert binding is not None
        assert binding.session_id == "external-uuid"
        assert binding.minted is False
        assert binding.source_descriptor is None

    def test_claude_wire_id_mismatch_is_not_minted(self) -> None:
        # A direct-id exchange whose wire id differs from the owned uuid (should not happen once claude
        # adopts the injected id, but guard it) is treated as un-owned: not minted, no descriptor.
        descriptor = encode_source_descriptor(
            FileTailSource(path="/home/u/.claude/projects/-w/owned.jsonl", format="claude_jsonl")
        )
        entry = make_index_entry(provider="anthropic")
        artifacts = make_artifacts(make_request_ir(session_id="other-uuid"))
        binding = bind_exchange(
            entry,
            artifacts,
            _run_facts(
                cli="claude",
                owned_native_session_id="owned-uuid",
                owned_source_descriptor=descriptor,
            ),
        )
        assert binding is not None
        assert binding.minted is False
        assert binding.source_descriptor is None

    def test_non_owned_codex_id_stays_undescribed(self) -> None:
        # A codex wire id TM did NOT seed (e.g. a forked subagent thread) must not borrow the owned
        # session's descriptor — it stays pending (no cursor) rather than mis-joining (regression c).
        descriptor = encode_source_descriptor(
            FileTailSource(path="/home/u/.codex/sessions/r-owned.jsonl", format="codex_rollout")
        )
        entry = make_index_entry(provider="codex")
        artifacts = make_artifacts(make_request_ir(session_id="native-OTHER"))
        binding = bind_exchange(
            entry,
            artifacts,
            _run_facts(
                cli="codex",
                owned_native_session_id="native-OWNED",
                owned_source_descriptor=descriptor,
            ),
        )
        assert binding is not None
        assert binding.source_descriptor is None  # not the owned id → no descriptor


class TestBuildWireJob:
    def test_row_reuses_req_stats_and_points_raw_dir(self, conn: sqlite3.Connection) -> None:
        req = ReqStats(system_chars=10, tools_chars=20, messages_chars=30)
        res = ResStats(stop_reason="end_turn", input_tokens=5, output_tokens=7)
        entry = make_index_entry(req=req, res=res, mutated_manually=True)
        artifacts = make_artifacts(make_request_ir(session_id="sess-1"))
        binding = bind_exchange(entry, artifacts, _run_facts())
        build_wire_job(entry, artifacts, binding).apply(conn)

        row = conn.execute(
            "SELECT session_id, run_id, provider, model, req_system_chars, req_tools_chars, "
            "req_messages_chars, req_tokens, res_tokens, stop_reason, mutated_manually, raw_dir, "
            "seq FROM wire_exchange WHERE exchange_id = 'ex1'"
        ).fetchone()
        assert row[0:4] == ("sess-1", "run1", "anthropic", "claude-3")
        assert row[4:7] == (10, 20, 30)  # ReqStats reused, not recomputed
        assert (row[7], row[8], row[9]) == (5, 7, "end_turn")
        assert row[10] == 1  # mutated_manually
        assert Path(row[11]).name == DiskStorageLayout().exchange_dir_name(entry.id, ts=entry.ts)
        assert row[12] == 0  # seq = MAX(seq)+1 within a fresh session
        assert (
            conn.execute("SELECT COUNT(*) FROM session WHERE session_id = 'sess-1'").fetchone()[0]
            == 1
        )

    def test_raw_dir_uses_provided_storage_root(self, conn: sqlite3.Connection) -> None:
        # Regression (roadtest2 #1): raw_dir is a tier-1 pointer that must be rooted at the
        # backend's ACTUAL storage root. When tier-1 is workspace-scoped (settings.storage_dir)
        # but raw_dir is recomputed on the global default root, the absolute pointer dangles and
        # GET /raw 404s though the bytes are safe on disk. The dir NAME alone (the prior assertion)
        # cannot catch this — the root is the failure surface.
        entry = make_index_entry()
        artifacts = make_artifacts(make_request_ir(session_id="sess-1"))
        binding = bind_exchange(entry, artifacts, _run_facts())
        ws_root = Path("/ws/scoped/root")
        build_wire_job(entry, artifacts, binding, storage_root=ws_root).apply(conn)

        raw_dir = conn.execute(
            "SELECT raw_dir FROM wire_exchange WHERE exchange_id = ?", (entry.id,)
        ).fetchone()[0]
        assert raw_dir == str(DiskStorageLayout(ws_root).new_exchange_dir(entry.id, now=entry.ts))
        assert Path(raw_dir).parent == ws_root  # rooted at the backend root, not the default

    def test_raw_dir_defaults_to_layout_default_root(self, conn: sqlite3.Connection) -> None:
        # No storage_root supplied (e.g. unit callers) → fall back to the default layout root,
        # preserving prior behaviour.
        entry = make_index_entry()
        artifacts = make_artifacts(make_request_ir(session_id="sess-1"))
        binding = bind_exchange(entry, artifacts, _run_facts())
        build_wire_job(entry, artifacts, binding).apply(conn)

        raw_dir = conn.execute(
            "SELECT raw_dir FROM wire_exchange WHERE exchange_id = ?", (entry.id,)
        ).fetchone()[0]
        assert Path(raw_dir).parent == DiskStorageLayout().root

    def test_null_session_when_uncorrelated(self, conn: sqlite3.Connection) -> None:
        entry = make_index_entry()
        artifacts = make_artifacts(make_request_ir(session_id=None))
        build_wire_job(entry, artifacts, None).apply(conn)
        session_id, seq = conn.execute(
            "SELECT session_id, seq FROM wire_exchange WHERE exchange_id = 'ex1'"
        ).fetchone()
        assert session_id is None
        assert seq is None  # seq is per-session; NULL while uncorrelated
        assert conn.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 0

    def test_edges_ordered_system_tools_messages_response(self, conn: sqlite3.Connection) -> None:
        request = make_request_ir(
            session_id="sess-1",
            system=[SystemPart(text="S")],
            tools=[TOOL_BASH],
            messages=[Message(role="user", content=[TextBlock(text="U")])],
        )
        entry = make_index_entry()
        artifacts = make_artifacts(request, make_response_ir())
        binding = bind_exchange(entry, artifacts, _run_facts())
        build_wire_job(entry, artifacts, binding).apply(conn)
        edges = conn.execute(
            "SELECT pos, role, section FROM exchange_block WHERE exchange_id = 'ex1' ORDER BY pos"
        ).fetchall()
        assert edges == [
            (0, "system", "system"),
            (1, "system", "tools"),
            (2, "user", "messages"),
            (3, "assistant", "response"),
        ]

    def test_idempotent_reingest_replaces_edges_and_keeps_one_row(
        self, conn: sqlite3.Connection
    ) -> None:
        request = make_request_ir(
            session_id="sess-1", messages=[Message(role="user", content=[TextBlock(text="U")])]
        )
        entry = make_index_entry()
        artifacts = make_artifacts(request)
        binding = bind_exchange(entry, artifacts, _run_facts())
        build_wire_job(entry, artifacts, binding).apply(conn)
        build_wire_job(entry, artifacts, binding).apply(conn)
        assert conn.execute("SELECT COUNT(*) FROM wire_exchange").fetchone()[0] == 1
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM exchange_block WHERE exchange_id = 'ex1'"
            ).fetchone()[0]
            == 1
        )

    def test_seq_backfilled_when_correlation_arrives_later(self, conn: sqlite3.Connection) -> None:
        entry = make_index_entry()
        # First write is uncorrelated: session_id and seq are both NULL.
        build_wire_job(entry, make_artifacts(make_request_ir(session_id=None)), None).apply(conn)
        assert conn.execute(
            "SELECT session_id, seq FROM wire_exchange WHERE exchange_id = 'ex1'"
        ).fetchone() == (None, None)
        # A later correlation upsert backfills session_id AND assigns seq (not left NULL).
        artifacts = make_artifacts(make_request_ir(session_id="sess-1"))
        binding = bind_exchange(entry, artifacts, _run_facts())
        build_wire_job(entry, artifacts, binding).apply(conn)
        assert conn.execute(
            "SELECT session_id, seq FROM wire_exchange WHERE exchange_id = 'ex1'"
        ).fetchone() == ("sess-1", 0)

    def test_seq_increments_per_session_and_is_preserved_on_reingest(
        self, conn: sqlite3.Connection
    ) -> None:
        run_facts = _run_facts()
        artifacts = make_artifacts(make_request_ir(session_id="sess-1"))
        first = make_index_entry(exchange_id="a")
        second = make_index_entry(exchange_id="b")
        build_wire_job(first, artifacts, bind_exchange(first, artifacts, run_facts)).apply(conn)
        build_wire_job(second, artifacts, bind_exchange(second, artifacts, run_facts)).apply(conn)
        assert dict(conn.execute("SELECT exchange_id, seq FROM wire_exchange").fetchall()) == {
            "a": 0,
            "b": 1,
        }
        # Re-ingesting an already-correlated exchange must not renumber it.
        build_wire_job(first, artifacts, bind_exchange(first, artifacts, run_facts)).apply(conn)
        assert (
            conn.execute("SELECT seq FROM wire_exchange WHERE exchange_id = 'a'").fetchone()[0] == 0
        )


class TestMakeIndexSink:
    def test_end_to_end_capture_creates_wire_and_session_rows(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "index.db")
        writer = IndexWriter(db_path, flush_ms=5)
        writer.start()
        sink = make_index_sink(writer, _run_facts())
        entry = make_index_entry(req=ReqStats(messages_chars=5))
        artifacts = make_artifacts(make_request_ir(session_id="sess-1"))
        sink(entry, artifacts)
        sink(entry, artifacts)  # idempotent re-capture
        writer.stop(drain=True)

        verify = connect(db_path)
        try:
            assert verify.execute("SELECT COUNT(*) FROM wire_exchange").fetchone()[0] == 1
            assert verify.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 1
            assert (
                verify.execute(
                    "SELECT session_id FROM wire_exchange WHERE exchange_id = 'ex1'"
                ).fetchone()[0]
                == "sess-1"
            )
        finally:
            verify.close()

    def test_sink_submits_wire_job_before_registering_cursor(self) -> None:
        # §5.2b ordering: the wire job (which upserts the session row with cli + source_descriptor)
        # must be accepted BEFORE cursor registration is scheduled — the canonical row write is
        # enqueued first, so the tailer never starts ahead of it.
        calls: list[str] = []

        class _RecordingWriter:
            def submit(self, job: IndexJob) -> None:
                calls.append(f"submit:{job.kind}")

        descriptor = encode_source_descriptor(
            FileTailSource(path="/home/u/.codex/sessions/r.jsonl", format="codex_rollout")
        )
        sink = make_index_sink(
            cast("IndexWriter", _RecordingWriter()),
            _run_facts(
                cli="codex", owned_native_session_id="native-9", owned_source_descriptor=descriptor
            ),
            lambda _binding: calls.append("on_binding"),
        )
        sink(
            make_index_entry(provider="codex"),
            make_artifacts(make_request_ir(session_id="native-9")),
        )
        assert calls == ["submit:wire", "on_binding"]  # row job accepted BEFORE cursor registration

    def test_owned_codex_transcript_turn_also_populates_session_row(
        self, conn: sqlite3.Connection
    ) -> None:
        # The other half of "row never empty regardless of order": a transcript turn landing FIRST
        # still yields cli=codex + source_descriptor, because the cursor's transcript_binding carries
        # cli (adapter.bind) + descriptor (register_session_cursor model_copy). Combined with the wire
        # path, whichever stream creates the row, it is non-empty (§5.2b empty-row symptom killed).
        descriptor = encode_source_descriptor(
            FileTailSource(path="/home/u/.codex/sessions/r.jsonl", format="codex_rollout")
        )
        binding = make_binding(
            synth_session_id("run1", "codex", "native-9"),
            provider="codex",
            cli="codex",
            native_session_id="native-9",
        ).model_copy(update={"source_descriptor": descriptor})
        turn = NormalizedTurn(
            turn_id="t1",
            session_id=binding.session_id,
            run_id="run1",
            provider="codex",
            cli="codex",
            role="assistant",
            seq=0,
            is_sidechain=False,
        )
        build_transcript_job(turn, binding).apply(conn)
        row = conn.execute(
            "SELECT cli, source_descriptor FROM session WHERE session_id = ?",
            (binding.session_id,),
        ).fetchone()
        assert row == ("codex", descriptor)

    def test_owned_codex_session_row_carries_cli_and_descriptor(self, tmp_path: Path) -> None:
        # Regression (d) at the unit level: an owned codex exchange lands a session row with
        # cli="codex" + the owned source_descriptor (via bind_exchange → build_wire_job →
        # upsert_session) BEFORE any transcript turn — directly killing the empty-session-row symptom.
        db_path = str(tmp_path / "index.db")
        writer = IndexWriter(db_path, flush_ms=5)
        writer.start()
        descriptor = encode_source_descriptor(
            FileTailSource(path="/home/u/.codex/sessions/r-native-9.jsonl", format="codex_rollout")
        )
        sink = make_index_sink(
            writer,
            _run_facts(
                cli="codex",
                owned_native_session_id="native-9",
                owned_source_descriptor=descriptor,
            ),
        )
        sink(
            make_index_entry(provider="codex"),
            make_artifacts(make_request_ir(session_id="native-9")),
        )
        writer.stop(drain=True)

        verify = connect(db_path)
        try:
            row = verify.execute(
                "SELECT cli, source_descriptor FROM session WHERE session_id = ?",
                (synth_session_id("run1", "codex", "native-9"),),
            ).fetchone()
            assert row == ("codex", descriptor)
        finally:
            verify.close()
