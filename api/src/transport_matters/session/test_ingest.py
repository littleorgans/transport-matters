from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from transport_matters.index.adapters.base import (
    FileTailSource,
    SessionBinding,
    TurnContext,
    encode_source_descriptor,
)
from transport_matters.index.adapters.claude import ClaudeAdapter
from transport_matters.index.test_replay_support import _seed_claude_run, _seed_codex_run
from transport_matters.session.artifacts import artifact_hash
from transport_matters.session.backfill import replay_transcript_run
from transport_matters.session.dao import AsyncSessionDao
from transport_matters.session.ingest import EventWrite, build_event, build_event_batch
from transport_matters.session.pool import async_connect, create_async_pool
from transport_matters.session.writer import SessionWriter

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


def test_replay_transcript_run_yields_snapshot_records_without_wire_index(tmp_path: Path) -> None:
    native = "019e0000-0000-7000-8000-00000000c0de"
    run_id = "run-codex"
    session_id = _seed_codex_run(tmp_path, run_id, native)
    root = next(tmp_path.glob(f"*/*/{run_id}"))
    (root / "index.jsonl").unlink()

    rows = list(replay_transcript_run(root))

    assert [(seq, record["type"]) for _binding, record, seq, _source in rows] == [
        (0, "session_meta"),
        (1, "response_item"),
    ]
    binding, _record, _seq, source = rows[0]
    assert binding.session_id == session_id
    assert binding.provider == "codex"
    assert binding.cli == "codex"
    assert binding.cwd == "/w"
    assert source.path.endswith("rollout.jsonl")


def test_replay_transcript_run_recovers_claude_record_cwd(tmp_path: Path) -> None:
    root, _cli_path = _seed_claude_run(tmp_path, "run-claude", _SESSION)
    snapshot = root / "transcripts" / f"{_SESSION}.jsonl"
    lines = snapshot.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["cwd"] = "/claude"
    lines[0] = json.dumps(first)
    snapshot.write_text("\n".join(lines) + "\n", encoding="utf-8")

    rows = list(replay_transcript_run(root))

    binding, _record, _seq, _source = rows[0]
    assert binding.cwd == "/claude"
