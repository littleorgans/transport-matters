"""Tailer: crash-safe complete-record iterate, poll/submit, registration, live event (§13.2)."""

import asyncio
import json
from typing import TYPE_CHECKING

from transport_matters import broadcast
from transport_matters.index.adapters.base import FileTailSource, NormalizedTurn, SessionBinding
from transport_matters.index.adapters.claude import ClaudeAdapter
from transport_matters.index.ingest import build_transcript_job
from transport_matters.index.tailer import (
    TailCursor,
    TranscriptTailer,
    iter_complete_records,
    register_session_cursor,
)
from transport_matters.index.writer import IndexWriter

if TYPE_CHECKING:
    from pathlib import Path

    from transport_matters.index.writer import IndexJob

_SESSION = "00000000-0000-4000-8000-000000000001"


def _binding(cwd: str = "/w") -> SessionBinding:
    return SessionBinding(
        session_id=_SESSION,
        provider="anthropic",
        run_id="run1",
        cwd=cwd,
        workspace_slug="s",
        workspace_hash="h",
        started_at="t",
        cli="claude",
        native_session_id=_SESSION,
        minted=False,
    )


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
