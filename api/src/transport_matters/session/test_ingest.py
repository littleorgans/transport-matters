from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import psycopg

from transport_matters.index.adapters.base import (
    FileTailSource,
    SessionBinding,
    TurnContext,
    encode_source_descriptor,
)
from transport_matters.index.adapters.claude import ClaudeAdapter
from transport_matters.index.tailer import TailCursor, TranscriptTailer
from transport_matters.index.test_replay_support import _seed_claude_run, _seed_codex_run
from transport_matters.session import dao_rows, ingest
from transport_matters.session.artifacts import artifact_hash
from transport_matters.session.async_dao import AsyncSessionDao
from transport_matters.session.backfill import replay_transcript_run
from transport_matters.session.ingest import (
    EventWrite,
    RecordProvenance,
    build_event,
    build_event_batch,
)
from transport_matters.session.models import (
    DeadLetterWrite,
    EventKind,
    EventRow,
    SessionPurpose,
    SessionVisibility,
)
from transport_matters.session.pool import async_connect, create_async_pool
from transport_matters.session.quarantine import DEAD_LETTER_RAW_MAX_BYTES
from transport_matters.session.writer import CommitResult, SessionWriter

if TYPE_CHECKING:
    from pathlib import Path

    from transport_matters.session.testing import TestDb

_SESSION = "00000000-0000-4000-8000-000000000111"
_IMAGE = b"image-bytes"


def _binding() -> SessionBinding:
    descriptor = encode_source_descriptor(
        FileTailSource(path="/tmp/transcript.jsonl", format="claude_jsonl")
    )
    return SessionBinding(
        session_id=_SESSION,
        provider="anthropic",
        run_id="run1",
        cwd="/workspace",
        workspace_slug="workspace",
        workspace_hash="hash1",
        started_at=datetime(2026, 6, 6, tzinfo=UTC).isoformat(),
        cli="claude",
        native_session_id=_SESSION,
        minted=True,
        source_descriptor=descriptor,
        home_dir="/tmp/home",
    )


def _turn_record() -> dict[str, Any]:
    # Any: native transcript record JSON carries provider scoped fields.
    return {
        "type": "assistant",
        "uuid": "turn1",
        "parentUuid": None,
        "sessionId": _SESSION,
        "isSidechain": False,
        "timestamp": "2026-06-06T00:00:01Z",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "hello artifact"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(_IMAGE).decode("ascii"),
                    },
                },
            ],
        },
    }


def _meta_record() -> dict[str, Any]:
    # Any: native transcript record JSON carries provider scoped fields.
    return {
        "type": "session_meta",
        "payload": {"id": "native1", "timestamp": "2026-06-06T00:00:02Z"},
    }


def _plain_turn_record(uuid: str, text: str) -> dict[str, Any]:
    # Any: native transcript record JSON carries provider scoped fields.
    return {
        "type": "assistant",
        "uuid": uuid,
        "parentUuid": None,
        "sessionId": _SESSION,
        "isSidechain": False,
        "timestamp": "2026-06-06T00:00:01Z",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def _event_row(seq: int, raw: dict[str, Any]) -> EventWrite:
    return EventWrite(
        event=EventRow(
            session_id=_SESSION,
            seq=seq,
            kind=EventKind.TURN,
            native_turn_id=f"turn{seq}",
            run_id="run1",
            provider="anthropic",
            cli="claude",
            raw=raw,
            source_path="/tmp/transcript.jsonl",
            source_line=seq,
        ),
        provenance=RecordProvenance(byte_start=seq * 10, byte_end=seq * 10 + 9),
    )


def _event_writes() -> tuple[SessionBinding, list[EventWrite]]:
    binding = _binding()
    adapter = ClaudeAdapter()
    record = _turn_record()
    ctx = TurnContext(binding=binding, source_path="/tmp/transcript.jsonl", seq=0, source_line=0)
    turn = adapter.normalize(record, ctx)
    assert turn is not None
    turn_write = build_event(record, turn, ctx)
    meta_ctx = ctx.model_copy(update={"seq": 1, "source_line": 1, "model": "claude-opus"})
    meta_write = build_event(_meta_record(), None, meta_ctx)
    return binding, [turn_write, meta_write]


async def test_session_writer_commits_raw_ir_meta_artifacts_and_reingest(
    test_db: TestDb,
) -> None:
    binding, writes = _event_writes()
    batch = build_event_batch(binding, writes)
    loop = asyncio.get_running_loop()
    writer = SessionWriter(
        create_async_pool(test_db.database_url, min_size=1, max_size=1), loop=loop
    )
    try:
        first = await loop.run_in_executor(None, writer.submit_blocking, batch)
        second = await loop.run_in_executor(None, writer.submit_blocking, batch)
        assert (first.ok, first.committed, first.last_seq) == (True, 2, 1)
        assert (second.ok, second.committed, second.last_seq) == (True, 2, 1)

        async with await async_connect(test_db.database_url, autocommit=True) as conn:
            dao = AsyncSessionDao(conn)
            events = await dao.get_events(_SESSION)
            assert len(events) == 2
            turn, meta = events
            assert turn.kind == "turn"
            assert turn.raw["uuid"] == "turn1"
            assert turn.ir is not None
            assert turn.ir["parts"][0] == {
                "type": "text",
                "text": "hello artifact",
                "provider_data": None,
            }
            assert turn.ir["parts"][1] == {
                "type": "image",
                "artifact_hash": artifact_hash(_IMAGE),
                "media_type": "image/png",
            }
            assert turn.search_text == "hello artifact"
            assert meta.kind == "meta"
            assert meta.raw["type"] == "session_meta"
            assert meta.ir is None
            assert meta.model == "claude-opus"

            artifact = await dao.get_artifact(artifact_hash(_IMAGE))
            assert artifact is not None
            assert artifact.data == _IMAGE
            cursor = await conn.execute(
                """
                SELECT count(*) AS n
                FROM event_artifact
                WHERE session_id = %s AND seq = %s
                """,
                (_SESSION, 0),
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row["n"] == 1
    finally:
        await writer.aclose()


async def test_session_writer_persists_internal_session_classification(
    test_db: TestDb,
) -> None:
    binding = _binding().model_copy(update={"session_id": "internal-session"})
    batch = build_event_batch(
        binding,
        [],
        session_purpose=SessionPurpose.INTERNAL_SUMMARY,
        session_visibility=SessionVisibility.HIDDEN,
    )
    loop = asyncio.get_running_loop()
    writer = SessionWriter(
        create_async_pool(test_db.database_url, min_size=1, max_size=1), loop=loop
    )
    try:
        result = await loop.run_in_executor(None, writer.submit_blocking, batch)
        assert (result.ok, result.committed, result.last_seq) == (True, 0, None)

        async with await async_connect(test_db.database_url, autocommit=True) as conn:
            row = await AsyncSessionDao(conn).get_session("internal-session")
            assert row is not None
            assert row.session_purpose == SessionPurpose.INTERNAL_SUMMARY
            assert row.session_visibility == SessionVisibility.HIDDEN
    finally:
        await writer.aclose()


async def test_tailer_quarantines_program_limit_poison_and_advances(
    test_db: TestDb, tmp_path: Path, monkeypatch: Any
) -> None:
    poison_text = " ".join(f"oversized{i}" for i in range(140_000))
    records = [
        _plain_turn_record("good1", "before"),
        _plain_turn_record("poison1", poison_text),
        _plain_turn_record("good2", "after"),
    ]
    lines = [json.dumps(record, separators=(",", ":")) + "\n" for record in records]
    path = tmp_path / "transcript.jsonl"
    path.write_text("".join(lines), encoding="utf-8")
    poison_start = len(lines[0].encode())
    poison_end = poison_start + len(lines[1].encode())
    poison_raw_len = len(lines[1].removesuffix("\n").encode())
    monkeypatch.setattr(ingest, "_cap_search_text", lambda text: text)

    binding = _binding().model_copy(update={"native_session_id": "native-authority"})
    loop = asyncio.get_running_loop()
    writer = SessionWriter(
        create_async_pool(test_db.database_url, min_size=1, max_size=1), loop=loop
    )
    results: list[CommitResult] = []

    def submit_batch(batch_binding: SessionBinding, events: list[EventWrite]) -> None:
        results.append(writer.submit_blocking(build_event_batch(batch_binding, events)))

    tailer = TranscriptTailer(
        build_record=build_event,
        submit_batch=submit_batch,
        quarantine_window=writer.quarantine_window_blocking,
    )
    cursor = TailCursor(
        binding=binding,
        source=FileTailSource(path=str(path), format="claude_jsonl"),
        adapter=ClaudeAdapter(),
    )
    tailer.register(cursor)

    try:
        await loop.run_in_executor(None, tailer.poll)

        assert cursor.byte_offset == len(path.read_bytes())
        assert [
            (result.committed, result.quarantined, result.quarantine_sqlstates)
            for result in results
        ] == [(2, 1, ("54000",))]
        async with await async_connect(test_db.database_url, autocommit=True) as conn:
            dao = AsyncSessionDao(conn)
            events = await dao.get_events(_SESSION)
            assert [event.seq for event in events] == [0, 2]
            dead = await (
                await conn.execute(
                    """
                    SELECT scope, seq, native_session_id, error_sqlstate, byte_start,
                           byte_end, attempts, raw_byte_len,
                           octet_length(raw_excerpt) AS excerpt_len
                    FROM event_dead_letter
                    WHERE session_id = %s
                    """,
                    (_SESSION,),
                )
            ).fetchone()
            assert dead is not None
            assert dead["scope"] == "record"
            assert dead["seq"] == 1
            assert dead["native_session_id"] == "native-authority"
            assert dead["error_sqlstate"] == "54000"
            assert (dead["byte_start"], dead["byte_end"]) == (poison_start, poison_end)
            assert dead["attempts"] == 1
            assert dead["raw_byte_len"] == poison_raw_len
            assert dead["excerpt_len"] == DEAD_LETTER_RAW_MAX_BYTES
    finally:
        await writer.aclose()


async def test_session_writer_quarantines_decoded_nul_poison(
    test_db: TestDb, monkeypatch: Any
) -> None:
    monkeypatch.setattr(dao_rows, "strip_decoded_nuls", lambda value: value)
    binding = _binding()
    writes = [
        _event_row(0, {"ok": "before"}),
        _event_row(1, {"bad": "\x00"}),
        _event_row(2, {"ok": "after"}),
    ]
    loop = asyncio.get_running_loop()
    writer = SessionWriter(
        create_async_pool(test_db.database_url, min_size=1, max_size=1), loop=loop
    )
    try:
        result = await loop.run_in_executor(
            None, writer.submit_blocking, build_event_batch(binding, writes)
        )
        assert (result.committed, result.quarantined, result.quarantine_sqlstates) == (
            2,
            1,
            ("22P05",),
        )
        async with await async_connect(test_db.database_url, autocommit=True) as conn:
            dao = AsyncSessionDao(conn)
            events = await dao.get_events(_SESSION)
            assert [event.seq for event in events] == [0, 2]
            dead = await (
                await conn.execute(
                    """
                    SELECT seq, error_sqlstate, byte_start, byte_end
                    FROM event_dead_letter
                    WHERE session_id = %s
                    """,
                    (_SESSION,),
                )
            ).fetchone()
            assert dead is not None
            assert (dead["seq"], dead["error_sqlstate"]) == (1, "22P05")
            assert (dead["byte_start"], dead["byte_end"]) == (10, 19)
    finally:
        await writer.aclose()


async def test_tailer_dead_letter_failure_aborts_batch_and_holds_cursor(
    test_db: TestDb, tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr(dao_rows, "strip_decoded_nuls", lambda value: value)
    dead_letter_attempts: list[int | None] = []

    async def fail_dead_letter(_self: AsyncSessionDao, letter: DeadLetterWrite) -> None:
        dead_letter_attempts.append(letter.seq)
        raise psycopg.OperationalError("dead-letter store unavailable")

    monkeypatch.setattr(AsyncSessionDao, "insert_dead_letter", fail_dead_letter)

    records = [
        _plain_turn_record("good1", "before"),
        _plain_turn_record("poison1", "middle"),
        _plain_turn_record("good2", "after"),
    ]
    records[1]["poison"] = "\x00"
    path = tmp_path / "transcript.jsonl"
    path.write_text(
        "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )

    binding = _binding()
    loop = asyncio.get_running_loop()
    writer = SessionWriter(
        create_async_pool(test_db.database_url, min_size=1, max_size=1), loop=loop
    )

    def submit_batch(batch_binding: SessionBinding, events: list[EventWrite]) -> None:
        writer.submit_blocking(build_event_batch(batch_binding, events))

    tailer = TranscriptTailer(
        build_record=build_event,
        submit_batch=submit_batch,
        quarantine_window=writer.quarantine_window_blocking,
    )
    cursor = TailCursor(
        binding=binding,
        source=FileTailSource(path=str(path), format="claude_jsonl"),
        adapter=ClaudeAdapter(),
    )
    tailer.register(cursor)

    try:
        await loop.run_in_executor(None, tailer.poll)

        assert dead_letter_attempts == [1]
        assert cursor.byte_offset == 0
        assert cursor.stat_signature is None
        async with await async_connect(test_db.database_url, autocommit=True) as conn:
            event_count = await (
                await conn.execute(
                    'SELECT count(*) AS n FROM "event" WHERE session_id = %s',
                    (_SESSION,),
                )
            ).fetchone()
            assert event_count is not None
            assert event_count["n"] == 0

            dead_letter_count = await (
                await conn.execute(
                    """
                    SELECT count(*) AS n
                    FROM event_dead_letter
                    WHERE session_id = %s
                    """,
                    (_SESSION,),
                )
            ).fetchone()
            assert dead_letter_count is not None
            assert dead_letter_count["n"] == 0
    finally:
        await writer.aclose()


async def test_dead_letter_insert_is_idempotent_and_caps_excerpt(test_db: TestDb) -> None:
    raw_excerpt = b"x" * (DEAD_LETTER_RAW_MAX_BYTES + 7)
    letter = DeadLetterWrite(
        session_id=_SESSION,
        scope="window",
        run_id="run1",
        native_session_id=_SESSION,
        provider="anthropic",
        cli="claude",
        byte_start=0,
        byte_end=10,
        error_class="UniqueViolation",
        error_message="constraint failed\x00",
        raw_excerpt=raw_excerpt,
        attempts=5,
    )
    async with await async_connect(test_db.database_url, autocommit=True) as conn:
        dao = AsyncSessionDao(conn)
        await dao.insert_dead_letter(letter)
        await dao.insert_dead_letter(letter)
        row = await (
            await conn.execute(
                """
                SELECT count(*) AS n, max(raw_byte_len) AS raw_byte_len,
                       max(octet_length(raw_excerpt)) AS excerpt_len,
                       max(error_message) AS error_message
                FROM event_dead_letter
                WHERE session_id = %s
                """,
                (_SESSION,),
            )
        ).fetchone()
        assert row is not None
        assert row["n"] == 1
        assert row["raw_byte_len"] == len(raw_excerpt)
        assert row["excerpt_len"] == DEAD_LETTER_RAW_MAX_BYTES
        assert row["error_message"] == "constraint failed"


async def test_session_writer_commits_oversized_search_text_with_tsv_budget(
    test_db: TestDb,
) -> None:
    binding = _binding()
    record = _turn_record()
    record["message"]["content"] = [
        {"type": "text", "text": " ".join(f"oversized{i}" for i in range(140_000))}
    ]
    ctx = TurnContext(binding=binding, source_path="/tmp/transcript.jsonl", seq=0, source_line=0)
    turn = ClaudeAdapter().normalize(record, ctx)
    assert turn is not None
    batch = build_event_batch(binding, [build_event(record, turn, ctx)])
    loop = asyncio.get_running_loop()
    writer = SessionWriter(
        create_async_pool(test_db.database_url, min_size=1, max_size=1), loop=loop
    )
    try:
        result = await loop.run_in_executor(None, writer.submit_blocking, batch)
        assert (result.ok, result.committed, result.last_seq) == (True, 1, 0)

        async with await async_connect(test_db.database_url, autocommit=True) as conn:
            cursor = await conn.execute(
                """
                SELECT
                    search_text,
                    octet_length(search_text) AS search_text_bytes,
                    content_tsv IS NOT NULL AS has_content_tsv
                FROM event
                WHERE session_id = %s AND seq = %s
                """,
                (_SESSION, 0),
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row["search_text"].endswith(ingest.SEARCH_TEXT_TRUNCATION_MARKER)
            assert row["search_text_bytes"] <= ingest.SEARCH_TEXT_MAX_BYTES
            assert row["has_content_tsv"] is True

            events = await AsyncSessionDao(conn).get_events(_SESSION)
            assert len(events) == 1
            persisted = events[0]
            assert (
                len(persisted.raw["message"]["content"][0]["text"].encode("utf-8"))
                > ingest.SEARCH_TEXT_MAX_BYTES
            )
            assert persisted.ir is not None
            assert (
                len(persisted.ir["parts"][0]["text"].encode("utf-8")) > ingest.SEARCH_TEXT_MAX_BYTES
            )
    finally:
        await writer.aclose()


def test_search_text_budget_truncates_on_utf8_boundary() -> None:
    capped = ingest._cap_search_text("\U0001f642" * ingest.SEARCH_TEXT_MAX_BYTES)

    assert capped.endswith(ingest.SEARCH_TEXT_TRUNCATION_MARKER)
    assert len(capped.encode("utf-8")) <= ingest.SEARCH_TEXT_MAX_BYTES
    assert "\ufffd" not in capped


def test_replay_transcript_run_yields_snapshot_records_without_wire_index(tmp_path: Path) -> None:
    native = "019e0000-0000-7000-8000-00000000c0de"
    run_id = "run-codex"
    session_id = _seed_codex_run(tmp_path, run_id, native)
    root = next(tmp_path.glob(f"*/*/{run_id}"))
    (root / "index.jsonl").unlink()

    rows = list(replay_transcript_run(root))

    assert [(seq, record["type"]) for _binding, record, seq, _source, _span in rows] == [
        (0, "session_meta"),
        (1, "response_item"),
    ]
    binding, _record, _seq, source, provenance = rows[0]
    assert binding.session_id == session_id
    assert binding.provider == "codex"
    assert binding.cli == "codex"
    assert binding.cwd == "/w"
    assert source.path.endswith("rollout.jsonl")
    assert provenance is not None
    assert provenance.byte_start == 0


def test_replay_transcript_run_recovers_claude_record_cwd(tmp_path: Path) -> None:
    root, _cli_path = _seed_claude_run(tmp_path, "run-claude", _SESSION)
    snapshot = root / "transcripts" / f"{_SESSION}.jsonl"
    lines = snapshot.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["cwd"] = "/claude"
    lines[0] = json.dumps(first)
    snapshot.write_text("\n".join(lines) + "\n", encoding="utf-8")

    rows = list(replay_transcript_run(root))

    binding, _record, _seq, _source, _span = rows[0]
    assert binding.cwd == "/claude"
