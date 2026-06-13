from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import psycopg
import psycopg.rows

from transport_matters.index.adapters.base import (
    FileTailSource,
    SessionBinding,
    encode_source_descriptor,
)
from transport_matters.index.adapters.claude import ClaudeAdapter
from transport_matters.index.adapters.codex import CodexAdapter
from transport_matters.index.sessions import synth_session_id
from transport_matters.index.tailer import TailCursor, TranscriptTailer
from transport_matters.session.backfill import replay_transcript_run
from transport_matters.session.dao import SessionDao
from transport_matters.session.ingest import EventWrite, build_event
from transport_matters.session.test_foundation import root_session
from transport_matters.storage.disk_layout import DiskStorageLayout
from transport_matters.storage.session_facts import OwnedSessionFacts, write_owned_session_facts

if TYPE_CHECKING:
    from transport_matters.session.testing import TestDb

_FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "subagents"
_PARENT_CLAUDE = "81574b77-8e32-4842-beb5-eff1ed10a1d6"
_CLAUDE_AGENT = "aa1ef3c921b947b83"
_PARENT_CODEX = "7bef1c5a-a0c5-45a3-89a6-ca0b5f54549d"
_CHILD_CODEX = "019ea67f-84f7-72d2-8b61-8173b07b845b"
_PARENT_CODEX_ITEMS = "11111111-1111-7111-8111-111111111111"
_CHILD_CODEX_ITEMS = "22222222-2222-7222-8222-222222222222"
_PARENT_CODEX_ITEMS_FILE = "rollout-2026-06-08T17-00-00-11111111-1111-7111-8111-111111111111.jsonl"
_CHILD_CODEX_ITEMS_FILE = "rollout-2026-06-08T17-00-01-22222222-2222-7222-8222-222222222222.jsonl"


def _source(path: Path) -> FileTailSource:
    return FileTailSource(path=str(path), format="jsonl")


def _binding(
    *,
    session_id: str,
    native_session_id: str,
    provider: str,
    cli: str,
    run_id: str,
    minted: bool = False,
) -> SessionBinding:
    return SessionBinding(
        session_id=session_id,
        provider=provider,
        run_id=run_id,
        cwd="/Users/alphab/Dev/LLM/DEV/helioy/transport-matters",
        workspace_slug="transport-matters",
        workspace_hash="hash1",
        started_at="2026-06-08T09:00:00Z",
        cli=cli,
        native_session_id=native_session_id,
        minted=minted,
    )


def _run_tailer(
    *,
    adapter: Any,
    binding: SessionBinding,
    source: FileTailSource,
) -> list[tuple[SessionBinding, list[EventWrite]]]:
    submitted: list[tuple[SessionBinding, list[EventWrite]]] = []

    def submit_batch(batch_binding: SessionBinding, events: list[EventWrite]) -> None:
        submitted.append((batch_binding, events))

    tailer = TranscriptTailer(build_record=build_event, submit_batch=submit_batch)
    tailer.register(TailCursor(binding=binding, source=source, adapter=adapter))
    tailer.poll()
    tailer.poll()
    return submitted


def test_tailer_materializes_claude_subagent_as_child_session() -> None:
    source = _source(_FIXTURES / "claude" / "parent.jsonl")
    parent = _binding(
        session_id=_PARENT_CLAUDE,
        native_session_id=_PARENT_CLAUDE,
        provider="anthropic",
        cli="claude",
        run_id="run-claude",
        minted=True,
    )

    submitted = _run_tailer(adapter=ClaudeAdapter(), binding=parent, source=source)

    child_id = synth_session_id(
        "run-claude",
        "anthropic",
        f"{_PARENT_CLAUDE}:claude-subagent:{_CLAUDE_AGENT}",
    )
    child_binding, child_events = next(
        batch for batch in submitted if batch[0].session_id == child_id
    )
    assert child_binding.parent_session_id == _PARENT_CLAUDE
    assert child_binding.forked_at_seq == 1
    assert child_binding.native_session_id == _CLAUDE_AGENT
    assert child_binding.title == "Summarize the transport-matters repo"
    assert [item.event.seq for item in child_events] == [0, 1]
    assert {item.event.session_id for item in child_events} == {child_id}
    assert {item.event.is_sidechain for item in child_events} == {False}


def test_tailer_materializes_codex_subagent_and_dedupes_fork_context_replay() -> None:
    source = _source(
        _FIXTURES
        / "codex"
        / "rollout-2026-06-08T16-09-22-7bef1c5a-a0c5-45a3-89a6-ca0b5f54549d.jsonl"
    )
    parent_id = synth_session_id("run-codex", "codex", _PARENT_CODEX)
    parent = _binding(
        session_id=parent_id,
        native_session_id=_PARENT_CODEX,
        provider="codex",
        cli="codex",
        run_id="run-codex",
    )

    submitted = _run_tailer(adapter=CodexAdapter(), binding=parent, source=source)

    child_id = synth_session_id("run-codex", "codex", _CHILD_CODEX)
    child_binding, child_events = next(
        batch for batch in submitted if batch[0].session_id == child_id
    )
    assert child_binding.parent_session_id == parent_id
    assert child_binding.forked_at_seq == 1
    assert child_binding.native_session_id == _CHILD_CODEX
    assert child_binding.title == "Singer"
    assert [item.event.seq for item in child_events] == [0, 1]
    first_ir = child_events[0].event.ir
    assert first_ir is not None
    first_text = first_ir["parts"][0]["text"]
    assert first_text.startswith("You are in /Users/alphab/Dev/LLM/DEV/helioy")
    assert first_text != "."
    assert child_events[0].event.source_line == 3


def test_tailer_materializes_codex_items_subagent_and_dedupes_replay() -> None:
    source = _source(_FIXTURES / "codex" / _PARENT_CODEX_ITEMS_FILE)
    parent_id = synth_session_id("run-codex-items", "codex", _PARENT_CODEX_ITEMS)
    parent = _binding(
        session_id=parent_id,
        native_session_id=_PARENT_CODEX_ITEMS,
        provider="codex",
        cli="codex",
        run_id="run-codex-items",
    )

    submitted = _run_tailer(adapter=CodexAdapter(), binding=parent, source=source)

    child_id = synth_session_id("run-codex-items", "codex", _CHILD_CODEX_ITEMS)
    child_binding, child_events = next(
        batch for batch in submitted if batch[0].session_id == child_id
    )
    assert child_binding.parent_session_id == parent_id
    assert child_binding.forked_at_seq == 1
    assert child_binding.native_session_id == _CHILD_CODEX_ITEMS
    assert child_binding.title == "Items"
    assert [item.event.seq for item in child_events] == [0, 1]
    assert [item.event.source_line for item in child_events] == [3, 4]
    first_ir = child_events[0].event.ir
    assert first_ir is not None
    assert [part["text"] for part in first_ir["parts"]] == [
        "Summarize repo",
        "Focus on tests",
    ]


def test_backfill_preserves_codex_items_subagent_source_lines(tmp_path: Path) -> None:
    run_id = "run-codex-items"
    parent_session_id = synth_session_id(run_id, "codex", _PARENT_CODEX_ITEMS)
    root = tmp_path / "proj" / "h1" / run_id
    root.mkdir(parents=True)
    parent_fixture = _FIXTURES / "codex" / _PARENT_CODEX_ITEMS_FILE
    child_fixture = _FIXTURES / "codex" / _CHILD_CODEX_ITEMS_FILE
    parent_rollout = root / _PARENT_CODEX_ITEMS_FILE
    child_rollout = root / _CHILD_CODEX_ITEMS_FILE
    parent_rollout.write_text(parent_fixture.read_text(encoding="utf-8"), encoding="utf-8")
    child_rollout.write_text(child_fixture.read_text(encoding="utf-8"), encoding="utf-8")
    snapshot = DiskStorageLayout(root).transcript_snapshot_path(parent_session_id)
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(parent_rollout.read_text(encoding="utf-8"), encoding="utf-8")
    write_owned_session_facts(
        root,
        OwnedSessionFacts(
            run_id=run_id,
            cli="codex",
            native_session_id=_PARENT_CODEX_ITEMS,
            minted=False,
            source_descriptor=encode_source_descriptor(
                FileTailSource(path=str(parent_rollout), format="codex_rollout")
            ),
        ),
    )

    rows = list(replay_transcript_run(root))

    child_session_id = synth_session_id(run_id, "codex", _CHILD_CODEX_ITEMS)
    child_rows = [row for row in rows if row[0].session_id == child_session_id]
    assert [
        (source_line, record["type"])
        for _binding, record, source_line, _source, _span in child_rows
    ] == [
        (3, "response_item"),
        (4, "response_item"),
    ]


def test_session_schema_allows_n_child_sessions_per_parent(test_db: TestDb) -> None:
    with psycopg.connect(test_db.database_url, row_factory=psycopg.rows.dict_row) as conn:
        dao = SessionDao(conn)
        parent = root_session("parent", native_session_id="native-parent")
        child_a = root_session("child-a", native_session_id="native-child-a").model_copy(
            update={"parent_session_id": "parent", "forked_at_seq": 1}
        )
        child_b = root_session("child-b", native_session_id="native-child-b").model_copy(
            update={"parent_session_id": "parent", "forked_at_seq": 2}
        )
        dao.upsert_session(parent)
        dao.upsert_session(child_a)
        dao.upsert_session(child_b)

        children = dao.list_child_sessions_for_owner("parent", owner="local")
        indexes = conn.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'session'
              AND indexname = 'session_parent_ix'
            """
        ).fetchall()

    assert [child.session_id for child in children] == ["child-a", "child-b"]
    assert indexes == [{"indexname": "session_parent_ix"}]
