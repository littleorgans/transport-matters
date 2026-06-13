"""Tailer quarantine retry and dead-letter handoff behavior."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg import errors

from transport_matters.index.tailer import TranscriptTailer
from transport_matters.index.test_tailer import _cursor, _user_line
from transport_matters.session.ingest import EventWrite, build_event
from transport_matters.session.quarantine import QUARANTINE_MAX_ATTEMPTS

if TYPE_CHECKING:
    from pathlib import Path

    from transport_matters.index.adapters.base import SessionBinding


class TestTailerQuarantine:
    def test_transient_psycopg_failure_retries_without_quarantine(self, tmp_path: Path) -> None:
        path = tmp_path / "t.jsonl"
        path.write_text(_user_line("u1", "hi") + "\n")
        submitted: list[EventWrite] = []
        calls: list[int] = []
        quarantine_calls: list[tuple[int, int]] = []

        def submit_batch(_binding: SessionBinding, events: list[EventWrite]) -> None:
            calls.append(len(events))
            if len(calls) == 1:
                raise psycopg.OperationalError("database unavailable")
            submitted.extend(events)

        def quarantine_window(
            _binding: SessionBinding,
            _source_path: str,
            byte_start: int,
            byte_end: int,
            _raw_excerpt: bytes,
            _exc: BaseException,
            _attempts: int,
        ) -> bool:
            quarantine_calls.append((byte_start, byte_end))
            return True

        tailer = TranscriptTailer(
            build_record=build_event,
            submit_batch=submit_batch,
            quarantine_window=quarantine_window,
        )
        tailer.register(_cursor(str(path)))

        tailer.poll()
        (cursor,) = tailer._snapshot()
        assert calls == [1]
        assert quarantine_calls == []
        assert cursor.byte_offset == 0
        assert cursor.quarantine_attempts == 0

        tailer.poll()
        assert calls == [1, 1]
        assert [write.event.native_turn_id for write in submitted] == ["u1"]
        assert cursor.byte_offset == len(path.read_bytes())
        assert quarantine_calls == []

    def test_other_failure_quarantines_window_after_attempt_cap(self, tmp_path: Path) -> None:
        path = tmp_path / "t.jsonl"
        payload = _user_line("u1", "hi") + "\n"
        path.write_text(payload)
        submit_calls: list[int] = []
        quarantine_calls: list[tuple[int, int, bytes, int]] = []

        def submit_batch(_binding: SessionBinding, _events: list[EventWrite]) -> None:
            submit_calls.append(1)
            raise errors.UniqueViolation("unexpected constraint failure")

        def quarantine_window(
            _binding: SessionBinding,
            _source_path: str,
            byte_start: int,
            byte_end: int,
            raw_excerpt: bytes,
            _exc: BaseException,
            attempts: int,
        ) -> bool:
            quarantine_calls.append((byte_start, byte_end, raw_excerpt, attempts))
            return True

        tailer = TranscriptTailer(
            build_record=build_event,
            submit_batch=submit_batch,
            quarantine_window=quarantine_window,
        )
        tailer.register(_cursor(str(path)))
        (cursor,) = tailer._snapshot()

        for _ in range(QUARANTINE_MAX_ATTEMPTS - 1):
            tailer.poll()
            assert cursor.byte_offset == 0

        tailer.poll()

        assert len(submit_calls) == QUARANTINE_MAX_ATTEMPTS
        assert quarantine_calls == [
            (0, len(payload.encode()), payload.encode(), QUARANTINE_MAX_ATTEMPTS)
        ]
        assert cursor.byte_offset == len(payload.encode())
        assert cursor.quarantine_attempts == 0
        assert cursor.stat_signature is not None

    def test_quarantine_write_failure_does_not_advance(self, tmp_path: Path) -> None:
        path = tmp_path / "t.jsonl"
        payload = _user_line("u1", "hi") + "\n"
        path.write_text(payload)
        quarantine_calls: list[int] = []

        def submit_batch(_binding: SessionBinding, _events: list[EventWrite]) -> None:
            raise errors.UniqueViolation("unexpected constraint failure")

        def quarantine_window(
            _binding: SessionBinding,
            _source_path: str,
            _byte_start: int,
            _byte_end: int,
            _raw_excerpt: bytes,
            _exc: BaseException,
            attempts: int,
        ) -> bool:
            quarantine_calls.append(attempts)
            raise psycopg.OperationalError("dead-letter store unavailable")

        tailer = TranscriptTailer(
            build_record=build_event,
            submit_batch=submit_batch,
            quarantine_window=quarantine_window,
        )
        tailer.register(_cursor(str(path)))
        (cursor,) = tailer._snapshot()

        for _ in range(QUARANTINE_MAX_ATTEMPTS):
            tailer.poll()

        assert cursor.byte_offset == 0
        assert cursor.stat_signature is None
        assert quarantine_calls == [QUARANTINE_MAX_ATTEMPTS]

    def test_poll_logs_repeated_failures_with_rate_limit(
        self, tmp_path: Path, monkeypatch: Any, caplog: Any
    ) -> None:
        path = tmp_path / "t.jsonl"
        path.write_text(_user_line("u1", "hi") + "\n")
        now = 100.0

        def monotonic() -> float:
            return now

        def submit_batch(_binding: SessionBinding, _events: list[EventWrite]) -> None:
            raise RuntimeError("database unavailable")

        monkeypatch.setattr("transport_matters.index.tailer.time.monotonic", monotonic)
        tailer = TranscriptTailer(build_record=build_event, submit_batch=submit_batch)
        tailer.register(_cursor(str(path)))

        caplog.set_level(logging.WARNING, logger="transport_matters.index.tailer")
        tailer.poll()
        tailer.poll()
        now = 131.0
        tailer.poll()

        messages = [record.getMessage() for record in caplog.records]
        assert sum("tailer poll failed for session" in message for message in messages) == 2
        assert any("suppressed 1 repeated tailer poll failure" in message for message in messages)
