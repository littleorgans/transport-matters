from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import psycopg
import psycopg.rows

from transport_matters.index.adapters.base import FileTailSource, SessionBinding
from transport_matters.index.adapters.claude import ClaudeAdapter
from transport_matters.index.adapters.codex import CodexAdapter
from transport_matters.index.sessions import synth_session_id
from transport_matters.index.tailer import TailCursor, TranscriptTailer
from transport_matters.session.dao import SessionDao
from transport_matters.session.ingest import EventWrite, build_event
from transport_matters.session.test_foundation import root_session

if TYPE_CHECKING:
    from transport_matters.session.testing import TestDb

_FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "subagents"
_PARENT_CLAUDE = "81574b77-8e32-4842-beb5-eff1ed10a1d6"
_CLAUDE_AGENT = "aa1ef3c921b947b83"
_PARENT_CODEX = "7bef1c5a-a0c5-45a3-89a6-ca0b5f54549d"
_CHILD_CODEX = "019ea67f-84f7-72d2-8b61-8173b07b845b"


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
