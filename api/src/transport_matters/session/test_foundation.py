from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation

from transport_matters.session import async_connect, connect, dao_rows
from transport_matters.session.artifacts import artifact_hash
from transport_matters.session.async_dao import AsyncSessionDao
from transport_matters.session.dao import SessionDao
from transport_matters.session.models import (
    DeadLetterWrite,
    EventRow,
    SessionPurpose,
    SessionRow,
    SessionVisibility,
)
from transport_matters.session.pool import (
    async_transaction,
    create_async_pool,
    create_pool,
    transaction,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from transport_matters.session.testing import TestDb


@pytest.fixture
def dao(test_db: TestDb) -> Iterator[SessionDao]:
    with connect(test_db.database_url, autocommit=True) as conn:
        yield SessionDao(conn)


def root_session(
    session_id: str = "s1", *, native_session_id: str | None = "native1"
) -> SessionRow:
    return SessionRow(
        session_id=session_id,
        provider="anthropic",
        cli="claude",
        run_id="run1",
        cwd="/workspace",
        workspace_slug="workspace",
        workspace_hash="hash1",
        native_session_id=native_session_id,
        minted=True,
        source_descriptor={"kind": "file_tail", "path": "/tmp/s1.jsonl", "format": "jsonl"},
        home_dir="/tmp/home",
        owner="local",
        started_at=datetime(2026, 6, 6, tzinfo=UTC),
    )


def dead_letter(
    byte_start: int = 0,
    *,
    session_id: str = "s1",
    run_id: str = "run1",
    native_session_id: str | None = "native1",
) -> DeadLetterWrite:
    return DeadLetterWrite(
        session_id=session_id,
        seq=byte_start,
        scope="record",
        run_id=run_id,
        native_session_id=native_session_id,
        provider="anthropic",
        cli="claude",
        source_path="/tmp/s1.jsonl",
        source_line=byte_start,
        event_kind="turn",
        byte_start=byte_start,
        byte_end=byte_start + 1,
        error_sqlstate="54000",
        error_class="ProgramLimitExceeded",
        error_message="tsvector too large",
        raw_excerpt=b"{}",
    )


def test_strip_decoded_nuls_recurses_json_compatible_values() -> None:
    sentinel = object()

    assert dao_rows.strip_decoded_nuls("a\x00b\x00c") == "abc"
    assert dao_rows.strip_decoded_nuls(
        {
            "ke\x00y": [
                "li\x00st",
                {"nested": ("tu\x00ple", 7, False, None)},
            ],
            "scalar": 42,
        }
    ) == {
        "key": [
            "list",
            {"nested": ("tuple", 7, False, None)},
        ],
        "scalar": 42,
    }
    assert dao_rows.strip_decoded_nuls(sentinel) is sentinel


def event(seq: int = 1, *, session_id: str = "s1", search_text: str = "alpha beta") -> EventRow:
    return EventRow(
        session_id=session_id,
        seq=seq,
        kind="turn",
        native_turn_id=f"turn{seq}",
        run_id="run1",
        provider="anthropic",
        cli="claude",
        role="assistant",
        ts=datetime(2026, 6, 6, 0, 0, seq, tzinfo=UTC),
        raw={"uuid": f"turn{seq}", "message": {"content": search_text}},
        ir={"parts": [{"type": "text", "text": search_text}]},
        source_path="/tmp/s1.jsonl",
        source_line=seq,
        search_text=search_text,
    )


def tool_result_event(
    seq: int = 1, *, session_id: str = "s1", text: str = "tool output"
) -> EventRow:
    return event(seq, session_id=session_id, search_text=text).model_copy(
        update={
            "ir": {
                "parts": [
                    {
                        "type": "tool_result",
                        "tool_use_id": f"tool-{seq}",
                        "content": [{"type": "text", "text": text}],
                    }
                ]
            },
            "search_text": text,
        }
    )


def test_session_upsert_strips_decoded_nuls(dao: SessionDao) -> None:
    session = root_session().model_copy(
        update={
            "title": "bad\x00title",
            "source_descriptor": {
                "kind": "file_tail",
                "path": "/tmp/s\x001.jsonl",
                "nested": ["x\x00y"],
            },
        }
    )

    inserted = dao.upsert_session(session)
    persisted = dao.get_session("s1")

    assert inserted.title == "badtitle"
    assert persisted is not None
    assert persisted.title == "badtitle"
    assert persisted.source_descriptor == {
        "kind": "file_tail",
        "path": "/tmp/s1.jsonl",
        "nested": ["xy"],
    }


def test_event_insert_strips_decoded_nuls_from_payload_boundaries(
    dao: SessionDao,
) -> None:
    dao.upsert_session(root_session())
    rows = [
        event(1, search_text="raw ok").model_copy(
            update={"raw": {"message": {"content": "raw\x00payload"}}}
        ),
        event(2, search_text="ir ok").model_copy(
            update={"ir": {"parts": [{"type": "text", "text": "ir\x00payload"}]}}
        ),
        tool_result_event(3, text="stdout\x00payload").model_copy(
            update={
                "raw": {"toolUseResult": {"stdout": "stdout\x00payload"}},
                "search_text": "tool ok",
            }
        ),
        event(4, search_text="search\x00payload").model_copy(
            update={
                "raw": {"message": {"content": "raw ok"}},
                "ir": {"parts": [{"type": "text", "text": "ir ok"}]},
            }
        ),
    ]

    for row in rows:
        dao.insert_event(row)

    persisted = dao.get_events_with_raw_for_owner("s1", owner="local")

    assert persisted[0].raw["message"]["content"] == "rawpayload"
    assert persisted[1].ir == {"parts": [{"type": "text", "text": "irpayload"}]}
    assert persisted[2].raw["toolUseResult"]["stdout"] == "stdoutpayload"
    assert persisted[2].ir == {
        "parts": [
            {
                "type": "tool_result",
                "tool_use_id": "tool-3",
                "content": [{"type": "text", "text": "stdoutpayload"}],
            }
        ]
    }
    assert persisted[3].search_text == "searchpayload"


def test_artifact_upsert_strips_decoded_nuls_from_media_type(dao: SessionDao) -> None:
    artifact = dao.upsert_artifact(b"poison-image", media_type="image/p\x00ng")
    persisted = dao.get_artifact(artifact.hash)

    assert artifact.media_type == "image/png"
    assert persisted is not None
    assert persisted.media_type == "image/png"


def test_schema_round_trips_session_event_and_artifact(dao: SessionDao) -> None:
    inserted_session = dao.upsert_session(root_session())
    inserted_event = dao.insert_event(event(search_text="generated microscope image"))
    artifact = dao.upsert_artifact(b"image-bytes", media_type="image/png")
    link = dao.link_artifact("s1", 1, artifact.hash, {"block_index": 0})

    assert dao.get_session("s1") == inserted_session
    assert dao.get_events("s1") == [inserted_event]
    assert dao.get_artifact(artifact.hash) == artifact
    assert artifact.hash == artifact_hash(b"image-bytes")
    assert artifact.data == b"image-bytes"
    assert link.artifact_hash == artifact.hash
    with_raw = dao.get_events_with_raw_for_owner("s1", owner="local")
    assert len(with_raw) == 1
    assert len(with_raw[0].artifacts) == 1
    assert with_raw[0].artifacts[0].artifact_hash == artifact.hash
    assert with_raw[0].artifacts[0].media_type == "image/png"
    assert with_raw[0].artifacts[0].size_bytes == len(b"image-bytes")


def test_session_classification_defaults_and_internal_values(dao: SessionDao) -> None:
    inserted = dao.upsert_session(root_session())
    assert inserted.session_purpose == SessionPurpose.USER
    assert inserted.session_visibility == SessionVisibility.USER_VISIBLE

    internal = root_session("internal", native_session_id="internal-native").model_copy(
        update={
            "session_purpose": SessionPurpose.INTERNAL_SUMMARY,
            "session_visibility": SessionVisibility.HIDDEN,
        }
    )
    persisted = dao.upsert_session(internal)

    assert persisted.session_purpose == SessionPurpose.INTERNAL_SUMMARY
    assert persisted.session_visibility == SessionVisibility.HIDDEN
    assert dao.get_session("internal") == persisted


def test_session_upsert_preserves_existing_classification(dao: SessionDao) -> None:
    dao.upsert_session(root_session("parent", native_session_id="parent-native"))
    continuation = root_session("continuation", native_session_id="continuation-native").model_copy(
        update={
            "session_purpose": SessionPurpose.CONTINUATION,
            "session_visibility": SessionVisibility.USER_VISIBLE,
            "parent_session_id": "parent",
            "forked_at_seq": 4,
        }
    )
    dao.upsert_session(continuation)

    dao.upsert_session(root_session("continuation", native_session_id="continuation-native"))

    persisted_continuation = dao.get_session("continuation")
    assert persisted_continuation is not None
    assert persisted_continuation.session_purpose == SessionPurpose.CONTINUATION
    assert persisted_continuation.session_visibility == SessionVisibility.USER_VISIBLE
    assert persisted_continuation.parent_session_id == "parent"
    assert persisted_continuation.forked_at_seq == 4

    internal = root_session(
        "internal-reupsert", native_session_id="internal-reupsert-native"
    ).model_copy(
        update={
            "session_purpose": SessionPurpose.INTERNAL_SUMMARY,
            "session_visibility": SessionVisibility.HIDDEN,
        }
    )
    dao.upsert_session(internal)

    dao.upsert_session(
        root_session("internal-reupsert", native_session_id="internal-reupsert-native")
    )

    persisted_internal = dao.get_session("internal-reupsert")
    assert persisted_internal is not None
    assert persisted_internal.session_purpose == SessionPurpose.INTERNAL_SUMMARY
    assert persisted_internal.session_visibility == SessionVisibility.HIDDEN


def test_get_events_for_owner_returns_lightweight_read_rows(dao: SessionDao) -> None:
    dao.upsert_session(root_session())
    dao.insert_event(
        event(search_text="large image").model_copy(update={"raw": {"image_base64": "x" * 200_000}})
    )

    rows = dao.get_events_for_owner("s1", owner="local")

    assert len(rows) == 1
    assert not hasattr(rows[0], "raw")
    assert rows[0].ir == {"parts": [{"type": "text", "text": "large image"}]}


def test_get_events_with_raw_for_owner_preserves_raw_and_scopes_owner(dao: SessionDao) -> None:
    dao.upsert_session(root_session())
    dao.upsert_session(
        root_session("s2", native_session_id="native2").model_copy(update={"owner": "other"})
    )
    dao.insert_event(event(search_text="raw event").model_copy(update={"raw": {"type": "mode"}}))
    dao.insert_event(event(session_id="s2", search_text="hidden"))

    rows = dao.get_events_with_raw_for_owner("s1", owner="local")

    assert len(rows) == 1
    assert rows[0].raw == {"type": "mode"}
    assert dao.get_events_with_raw_for_owner("s1", owner="other") == []


def test_session_native_uniqueness_scopes_owner_run_provider(dao: SessionDao) -> None:
    dao.upsert_session(root_session("s1", native_session_id="native"))
    dao.upsert_session(
        root_session("s2", native_session_id="native").model_copy(update={"run_id": "run2"})
    )
    dao.upsert_session(
        root_session("s3", native_session_id="native").model_copy(update={"owner": "other"})
    )

    with pytest.raises(UniqueViolation):
        dao.upsert_session(root_session("s4", native_session_id="native"))


def test_session_upsert_preserves_non_empty_cwd(dao: SessionDao) -> None:
    dao.upsert_session(root_session("s-cwd").model_copy(update={"cwd": "/real"}))
    dao.upsert_session(root_session("s-cwd").model_copy(update={"cwd": ""}))

    session = dao.get_session("s-cwd")
    assert session is not None
    assert session.cwd == "/real"


def test_fork_lineage_requires_parent_and_seq_together(dao: SessionDao) -> None:
    dao.upsert_session(root_session("parent"))
    fork = root_session("child", native_session_id="child-native").model_copy(
        update={"parent_session_id": "parent", "forked_at_seq": 4}
    )
    assert dao.upsert_session(fork).parent_session_id == "parent"

    with pytest.raises(CheckViolation):
        dao.upsert_session(
            root_session("bad-child").model_copy(update={"parent_session_id": "parent"})
        )

    with pytest.raises(ForeignKeyViolation):
        dao.upsert_session(
            root_session("orphan", native_session_id="orphan").model_copy(
                update={"parent_session_id": "missing", "forked_at_seq": 1}
            )
        )


def test_ir_gin_containment_search(dao: SessionDao) -> None:
    dao.upsert_session(root_session())
    dao.insert_event(
        event(search_text="tool run").model_copy(
            update={"ir": {"parts": [{"type": "tool_use", "name": "Bash", "input": {}}]}}
        )
    )
    dao.insert_event(
        event(2, search_text="tool run").model_copy(
            update={
                "kind": "meta",
                "ir": {"parts": [{"type": "tool_use", "name": "Bash", "input": {}}]},
            }
        )
    )

    matches = dao.events_matching_ir({"parts": [{"type": "tool_use", "name": "Bash"}]})

    assert [match.seq for match in matches] == [1]


def test_content_tsv_full_text_search(dao: SessionDao) -> None:
    dao.upsert_session(root_session())
    dao.insert_event(event(1, search_text="the quick brown fox"))
    dao.insert_event(event(2, search_text="slow red turtle"))
    dao.insert_event(
        event(3, search_text="quick fox hidden metadata").model_copy(update={"kind": "meta"})
    )

    matches = dao.search_event_text("quick fox")

    assert [match.seq for match in matches] == [1]


def test_sync_pool_and_transaction_lifecycle(test_db: TestDb) -> None:
    pool = create_pool(test_db.database_url, min_size=1, max_size=1)
    try:
        pool.open()
        with pool.connection() as conn, transaction(conn):
            row = conn.execute("SELECT 1 AS value").fetchone()
    finally:
        pool.close()

    assert row is not None
    assert row["value"] == 1


async def test_async_dao_round_trips_session_and_event(test_db: TestDb) -> None:
    async with await async_connect(test_db.database_url, autocommit=True) as conn:
        dao = AsyncSessionDao(conn)
        await dao.upsert_session(root_session("async-s1", native_session_id="async-native"))
        await dao.insert_event(event(session_id="async-s1"))

        rows = await dao.get_events("async-s1")

    assert [row.seq for row in rows] == [1]


async def test_async_artifact_upsert_strips_decoded_nuls_from_media_type(
    test_db: TestDb,
) -> None:
    async with await async_connect(test_db.database_url, autocommit=True) as conn:
        dao = AsyncSessionDao(conn)

        artifact = await dao.upsert_artifact(b"async-poison-image", media_type="image/p\x00ng")
        persisted = await dao.get_artifact(artifact.hash)

    assert artifact.media_type == "image/png"
    assert persisted is not None
    assert persisted.media_type == "image/png"


async def test_async_pool_and_transaction_lifecycle(test_db: TestDb) -> None:
    pool = create_async_pool(test_db.database_url, min_size=1, max_size=1)
    try:
        await pool.open()
        async with pool.connection() as conn, async_transaction(conn):
            cursor = await conn.execute("SELECT 1 AS value")
            row = await cursor.fetchone()
    finally:
        await pool.close()

    assert row is not None
    assert row["value"] == 1
