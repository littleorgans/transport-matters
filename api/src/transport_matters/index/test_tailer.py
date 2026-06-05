"""Tailer: crash-safe complete-record iterate, poll/submit, registration, live event (§13.2)."""

import asyncio
import json
from typing import TYPE_CHECKING

from transport_matters import broadcast
from transport_matters.index.adapters.base import (
    FileTailSource,
    NormalizedTurn,
    SessionBinding,
    encode_source_descriptor,
)
from transport_matters.index.adapters.claude import ClaudeAdapter
from transport_matters.index.adapters.codex import CodexAdapter
from transport_matters.index.conftest import make_binding
from transport_matters.index.ingest import build_transcript_job
from transport_matters.index.sessions import synth_session_id
from transport_matters.index.tailer import (
    TailCursor,
    TranscriptTailer,
    iter_complete_records,
    register_session_cursor,
)
from transport_matters.index.writer import IndexWriter

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from transport_matters.index.writer import IndexJob

_SESSION = "00000000-0000-4000-8000-000000000001"
_RUN = "run1"


def _codex_session_meta(native: str) -> str:
    return json.dumps(
        {
            "type": "session_meta",
            "payload": {
                "id": native,
                "timestamp": "2026-06-05T10:00:00.000Z",
                "cwd": "/w",
                "originator": "codex-tui",
                "cli_version": "0.137.0",
            },
        }
    )


def _codex_response_item(text: str) -> str:
    return json.dumps(
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            },
        }
    )


def _codex_wire_binding(native: str, descriptor: str | None) -> SessionBinding:
    """A codex wire binding as ``bind_exchange`` resolves it: synth session_id, cli unset on the
    wire side, ``source_descriptor`` present only for the session the launcher owns (§5.2b)."""
    return SessionBinding(
        session_id=synth_session_id(_RUN, "codex", native),
        provider="codex",
        run_id=_RUN,
        cwd="/w",
        workspace_slug="s",
        workspace_hash="h",
        started_at="t",
        cli=None,
        native_session_id=native,
        minted=False,
        source_descriptor=descriptor,
    )


def _binding(cwd: str = "/w") -> SessionBinding:
    return make_binding(_SESSION, cwd=cwd, workspace_slug="s", workspace_hash="h")


def _user_line(uuid: str, text: str) -> str:
    return json.dumps(
        {
            "type": "user",
            "uuid": uuid,
            "parentUuid": None,
            "sessionId": _SESSION,
            "isSidechain": False,
            "timestamp": "2026-06-05T12:00:00Z",
            "message": {"role": "user", "content": text},
        }
    )


def _cursor(path: str) -> TailCursor:
    return TailCursor(
        binding=_binding(),
        source=FileTailSource(path=path, format="claude_jsonl"),
        adapter=ClaudeAdapter(),
    )


class TestIterateSeam:
    def test_complete_records_only_leaves_trailing_partial(self) -> None:
        data = b'{"a":1}\n{"b":2}\n{"partial'
        records, consumed = iter_complete_records(data)
        assert records == [{"a": 1}, {"b": 2}]
        assert consumed == data.rfind(b"\n") + 1  # past the LAST newline; partial NOT consumed

    def test_no_newline_consumes_nothing(self) -> None:
        assert iter_complete_records(b'{"a":1}') == ([], 0)

    def test_skips_malformed_complete_lines(self) -> None:
        records, _ = iter_complete_records(b'{"ok":1}\nnot json\n{"ok":2}\n')
        assert records == [{"ok": 1}, {"ok": 2}]

    def test_shared_seam_drives_closed_file_backfill(self) -> None:
        # The SAME fn serves a closed-file backfill pass: a file ending in \n yields all records.
        data = b'{"a":1}\n{"b":2}\n'
        records, consumed = iter_complete_records(data)
        assert records == [{"a": 1}, {"b": 2}]
        assert consumed == len(data)


class TestTailerPoll:
    def test_poll_submits_complete_and_leaves_partial(self, tmp_path: Path) -> None:
        path = tmp_path / "t.jsonl"
        path.write_text(_user_line("u1", "hi") + "\n" + '{"type":"user","uuid":"u2"')
        submitted: list[IndexJob] = []
        tailer = TranscriptTailer(submitted.append)
        tailer.register(_cursor(str(path)))
        tailer.poll()
        assert [job.entity_id for job in submitted] == ["u1"]  # only the complete record

        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                f',"parentUuid":null,"sessionId":"{_SESSION}","isSidechain":false,'
                '"timestamp":"t","message":{"role":"user","content":"x"}}\n'
            )
        tailer.poll()
        assert [job.entity_id for job in submitted] == ["u1", "u2"]  # partial completed → consumed

    def test_register_is_idempotent(self, tmp_path: Path) -> None:
        submitted: list[IndexJob] = []
        tailer = TranscriptTailer(submitted.append)
        path = tmp_path / "t.jsonl"
        path.write_text(_user_line("u1", "hi") + "\n")
        cursor = _cursor(str(path))
        tailer.register(cursor)
        tailer.register(cursor)  # idempotent on session_id
        tailer.poll()
        assert [job.entity_id for job in submitted] == ["u1"]  # one cursor, one submit
        tailer.unregister(_SESSION)
        tailer.poll()
        assert len(submitted) == 1  # unregistered → no further submits


class TestRegisterCursor:
    async def test_register_session_cursor_locates_and_registers(self) -> None:
        tailer = TranscriptTailer(lambda _job: None)
        await register_session_cursor(tailer, ClaudeAdapter(), _binding(cwd="/w"))
        cursors = tailer._snapshot()
        assert len(cursors) == 1
        source = cursors[0].source
        assert isinstance(source, FileTailSource)
        assert source.path.endswith(f"-w/{_SESSION}.jsonl")
        assert cursors[0].byte_offset == 0  # catches turns written before registration

    async def test_codex_rebind_converges_and_uses_owned_descriptor(self, tmp_path: Path) -> None:
        # The transcript binding is RE-DERIVED through the adapter (bind() + RunContext go LIVE,
        # audit #2): for codex read-back the synth session_id must reproduce the wire side's (§7.2),
        # and the cursor binds the codex adapter's cli. Managed-mint (§5.2b): the source is the OWNED
        # rollout from the wire binding's source_descriptor — NOT a ~/.codex glob (the glob is gone).
        native = "019e0000-0000-7000-8000-00000000c0de"
        rollout = tmp_path / f"rollout-2026-06-05T10-00-00-{native}.jsonl"
        descriptor = encode_source_descriptor(
            FileTailSource(path=str(rollout), format="codex_rollout")
        )
        wire_binding = _codex_wire_binding(native, descriptor)
        tailer = TranscriptTailer(lambda _job: None)
        await register_session_cursor(tailer, CodexAdapter(), wire_binding)
        (cursor,) = tailer._snapshot()
        assert cursor.binding.session_id == wire_binding.session_id  # convergence: same synth id
        assert cursor.binding.cli == "codex"  # adapter-derived (was None on the wire binding)
        assert isinstance(cursor.source, FileTailSource)
        assert cursor.source.format == "codex_rollout"
        assert cursor.source.path == str(rollout)  # the OWNED path, byte-for-byte (no glob)

    async def test_owned_descriptor_cursor_tails_deterministically(self, tmp_path: Path) -> None:
        # Regression (a): seed the minimal rollout, register the cursor from the descriptor, append
        # one response_item, poll → EXACTLY one transcript job, tailed from the exact owned path.
        native = "019e0000-0000-7000-8000-0000000000aa"
        rollout = tmp_path / f"rollout-2026-06-05T10-00-00-{native}.jsonl"
        rollout.write_text(_codex_session_meta(native) + "\n", encoding="utf-8")
        descriptor = encode_source_descriptor(
            FileTailSource(path=str(rollout), format="codex_rollout")
        )
        submitted: list[IndexJob] = []
        tailer = TranscriptTailer(submitted.append)
        await register_session_cursor(
            tailer, CodexAdapter(), _codex_wire_binding(native, descriptor)
        )

        tailer.poll()  # only session_meta present → a normal no-op, NOT a locate miss
        assert submitted == []
        with rollout.open("a", encoding="utf-8") as handle:
            handle.write(_codex_response_item("hello") + "\n")
        tailer.poll()
        assert [job.kind for job in submitted] == ["transcript"]  # exactly one turn
        (cursor,) = tailer._snapshot()
        assert isinstance(cursor.source, FileTailSource)
        assert cursor.source.path == str(rollout)  # tailed from the exact owned path

    async def test_non_owned_codex_binding_registers_no_cursor(self) -> None:
        # Regression (c): a codex wire id TM did not seed has no owned descriptor (bind_exchange left
        # it None). register_session_cursor registers NO cursor — it stays pending: no glob, no
        # error, no busy-poll (the old window-id phantom path is gone).
        submitted: list[IndexJob] = []
        tailer = TranscriptTailer(submitted.append)
        await register_session_cursor(
            tailer,
            CodexAdapter(),
            _codex_wire_binding("019e0000-0000-7000-8000-0000000000ff", None),
        )
        assert tailer._snapshot() == []  # nothing registered
        tailer.poll()  # nothing to poll
        assert submitted == []

    async def test_five_managed_sessions_same_cwd_no_cross_binding(self, tmp_path: Path) -> None:
        # Regression (b): 5 managed codex sessions in the SAME cwd, each a unique uuid + owned
        # rollout path, one response each. Assert zero cross-binding — every cursor tails ITS own
        # path and emits ITS own session's turn (no newest-glob: each path is owned, not discovered).
        natives = [f"019e0000-0000-7000-8000-0000000{i:05d}" for i in range(5)]
        paths: list[str] = []
        submitted: list[IndexJob] = []
        tailer = TranscriptTailer(submitted.append)
        for i, native in enumerate(natives):
            rollout = tmp_path / f"rollout-2026-06-05T10-00-0{i}-{native}.jsonl"
            rollout.write_text(
                _codex_session_meta(native) + "\n" + _codex_response_item(f"msg-{i}") + "\n",
                encoding="utf-8",
            )
            paths.append(str(rollout))
            descriptor = encode_source_descriptor(
                FileTailSource(path=str(rollout), format="codex_rollout")
            )
            await register_session_cursor(
                tailer, CodexAdapter(), _codex_wire_binding(native, descriptor)
            )

        cursors = tailer._snapshot()
        assert len(cursors) == 5  # five distinct cursors (distinct synth session_ids)
        # each cursor is bound to ITS OWN owned path — no two share, none point at "newest"
        source_paths = set()
        for c in cursors:
            assert isinstance(c.source, FileTailSource)
            source_paths.add(c.source.path)
        assert source_paths == set(paths)
        expected_ids = {synth_session_id(_RUN, "codex", n) for n in natives}
        assert {c.binding.session_id for c in cursors} == expected_ids

        tailer.poll()
        # one turn per session, and each turn's session_id is the one whose rollout it came from
        emitted = {job.event["session_id"] for job in submitted if job.event is not None}
        assert len(submitted) == 5
        assert emitted == expected_ids  # zero cross-binding


class TestCodexModelThreading:
    def test_tail_threads_turn_context_model_onto_codex_turns(
        self, conn: sqlite3.Connection
    ) -> None:
        # codex carries its model in a separate `turn_context` record (which normalize skips), so the
        # tailer must thread it forward — else every codex transcript_turn lands model=NULL (review F1).
        from pathlib import Path as _Path

        from transport_matters.index.adapters.codex import CodexAdapter
        from transport_matters.index.sessions import synth_session_id

        fixture = (
            _Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "codex_rollout.jsonl"
        )
        native = "019e0000-0000-7000-8000-00000000c0de"
        binding = make_binding(
            synth_session_id("run1", "codex", native),
            provider="codex",
            cli="codex",
            native_session_id=native,
        )
        jobs: list[IndexJob] = []
        tailer = TranscriptTailer(jobs.append)
        tailer.register(
            TailCursor(
                binding=binding,
                source=FileTailSource(path=str(fixture), format="codex_rollout"),
                adapter=CodexAdapter(),
            )
        )
        tailer.poll()
        for job in jobs:
            job.apply(conn)

        models = [m for (m,) in conn.execute("SELECT model FROM transcript_turn").fetchall()]
        assert models  # the 7 response_items became turns
        assert all(m == "gpt-5-codex" for m in models)  # threaded from turn_context.payload.model


class TestLiveEvent:
    async def test_writer_emits_transcript_turn_after_commit(self, tmp_path: Path) -> None:
        loop = asyncio.get_running_loop()
        writer = IndexWriter(str(tmp_path / "index.db"), flush_ms=5, loop=loop, emit=broadcast.emit)
        writer.start()
        queue = broadcast.subscribe()
        try:
            turn = NormalizedTurn(
                turn_id="t1",
                session_id=_SESSION,
                run_id="run1",
                provider="anthropic",
                cli="claude",
                role="assistant",
                seq=7,
                is_sidechain=False,
            )
            writer.submit(build_transcript_job(turn, _binding()))
            await loop.run_in_executor(None, lambda: writer.stop(drain=True))
            event = json.loads(await asyncio.wait_for(queue.get(), timeout=2.0))
            assert event["type"] == "transcript_turn"
            assert (event["turn_id"], event["session_id"], event["seq"]) == ("t1", _SESSION, 7)
        finally:
            broadcast.unsubscribe(queue)
