"""Tailer: crash-safe complete-record iterate, poll/submit, registration, live event (§13.2)."""

import asyncio
import json
from typing import TYPE_CHECKING

from transport_matters import broadcast
from transport_matters.index.adapters.base import FileTailSource, NormalizedTurn, SessionBinding
from transport_matters.index.adapters.claude import ClaudeAdapter
from transport_matters.index.conftest import make_binding
from transport_matters.index.ingest import build_transcript_job
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

    def test_poll_is_graceful_when_rollout_missing(self, tmp_path: Path) -> None:
        # The frame-1 phantom (a codex window-id with no rollout, §15 risk 2) registers a cursor on a
        # non-existent path. Poll must no-op cleanly — no error, no submitted jobs — and stay ready if
        # the file ever appears (the cursor is isolated; it never mis-joins the real thread).
        from transport_matters.index.adapters.codex import CodexAdapter

        submitted: list[IndexJob] = []
        tailer = TranscriptTailer(submitted.append)
        missing = tmp_path / "rollout-does-not-exist.jsonl"
        tailer.register(
            TailCursor(
                binding=_binding(),
                source=FileTailSource(path=str(missing), format="codex_rollout"),
                adapter=CodexAdapter(),
            )
        )
        tailer.poll()  # must not raise on a missing path
        tailer.poll()  # idempotent: still no busy-read / error
        assert submitted == []

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

    async def test_register_session_cursor_rebinds_readback_via_adapter(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        # The transcript binding is RE-DERIVED through the adapter (bind() + RunContext go LIVE here,
        # audit #2): for codex read-back the synth session_id must reproduce the wire side's (§7.2),
        # and the cursor binds the codex adapter's cli + rollout source.
        from pathlib import Path as _Path

        from transport_matters.index.adapters.codex import CodexAdapter
        from transport_matters.index.sessions import synth_session_id

        native = "019e0000-0000-7000-8000-00000000c0de"
        monkeypatch.setattr(_Path, "home", lambda: tmp_path)  # type: ignore[attr-defined]
        expected = synth_session_id("run1", "codex", native)
        wire_binding = SessionBinding(
            session_id=expected,
            provider="codex",
            run_id="run1",
            cwd="/w",
            workspace_slug="s",
            workspace_hash="h",
            started_at="t",
            cli=None,  # the wire run_facts carries no cli; the adapter supplies it on re-bind
            native_session_id=native,
            minted=False,
        )
        tailer = TranscriptTailer(lambda _job: None)
        await register_session_cursor(tailer, CodexAdapter(), wire_binding)
        (cursor,) = tailer._snapshot()
        assert cursor.binding.session_id == expected  # convergence: re-bind reproduces wire id
        assert cursor.binding.cli == "codex"  # adapter-derived (was None on the wire binding)
        assert isinstance(cursor.source, FileTailSource)
        assert cursor.source.format == "codex_rollout"


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
