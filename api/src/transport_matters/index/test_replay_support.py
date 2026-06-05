"""Shared tier-1 run-dir seeders for the replay test suites (8c-i replay + 8c-ii boot auto-replay).

A run dir is seeded with exactly what tier-1 holds — ``index.jsonl`` + ``*.ir.json`` (wire),
``transcripts/<sid>.jsonl`` (the 8b-i snapshot), and ``sessions.json`` (the 8b-ii owned facts) — so
replay/backfill/reconcile/boot tests all build identical fixtures from one place (DRY; §13). Names are
kept stable (underscore-prefixed) so the existing ``test_rebuild`` call sites reference them
unchanged; test code may import these from a shared ``_support`` module per the import-boundary rule.
"""

import json
from typing import TYPE_CHECKING

from transport_matters.index.adapters.base import FileTailSource, encode_source_descriptor
from transport_matters.index.sessions import synth_session_id
from transport_matters.index.writer import IndexWriter
from transport_matters.ir import Message, SystemPart, TextBlock
from transport_matters.storage.disk_layout import DiskStorageLayout
from transport_matters.storage.session_facts import OwnedSessionFacts, write_owned_session_facts
from transport_matters.storage.test_exchange_support import (
    make_artifacts,
    make_index_entry,
    make_request_ir,
    make_response_ir,
)

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from transport_matters.storage.base import ExchangeArtifacts, IndexEntry

_SLUG = "proj"
_HASH = "h1"


def _run_dir(workspaces_root: Path, run_id: str) -> Path:
    root = workspaces_root / _SLUG / _HASH / run_id
    root.mkdir(parents=True)
    return root


def _write_wire(root: Path, entry: IndexEntry, artifacts: ExchangeArtifacts) -> None:
    """Persist one exchange the way the recorder does: an ``index.jsonl`` line + IR artifacts."""
    layout = DiskStorageLayout(root)
    with layout.index_path.open("a", encoding="utf-8") as handle:
        handle.write(entry.model_dump_json() + "\n")
    exchange_dir = layout.new_exchange_dir(entry.id, now=entry.ts)
    exchange_dir.mkdir(parents=True, exist_ok=True)
    paths = layout.artifact_paths(exchange_dir)
    paths.request_ir.write_text(artifacts.request_ir.model_dump_json(), encoding="utf-8")
    if artifacts.response_ir is not None:
        paths.response_ir.write_text(artifacts.response_ir.model_dump_json(), encoding="utf-8")


def _claude_user(uuid: str, text: str, sid: str) -> str:
    return json.dumps(
        {
            "type": "user",
            "uuid": uuid,
            "parentUuid": None,
            "sessionId": sid,
            "isSidechain": False,
            "timestamp": "2026-06-05T12:00:00Z",
            "message": {"role": "user", "content": text},
        }
    )


def _claude_assistant(uuid: str, parent: str, text: str, sid: str) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "uuid": uuid,
            "parentUuid": parent,
            "sessionId": sid,
            "isSidechain": False,
            "timestamp": "2026-06-05T12:00:01Z",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
        }
    )


def _descriptor(path: Path) -> str:
    return encode_source_descriptor(FileTailSource(path=str(path), format="claude_jsonl"))


def _codex_session_meta(native: str) -> str:
    return json.dumps({"type": "session_meta", "payload": {"id": native, "cwd": "/w"}})


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


def _seed_codex_run(workspaces_root: Path, run_id: str, native: str) -> str:
    """Seed an owned-codex run (read-back synth PK); return the synthesized ``session_id``.

    codex is ``minted=False``: the session_id is ``synth_session_id(run_id, "codex", native)`` on
    BOTH streams, and the snapshot is keyed by that synth id — so a faithful rebuild must reconstruct
    it from ``sessions.json`` the same way (the explicit reviewer check for the read-back path).
    """
    session_id = synth_session_id(run_id, "codex", native)
    root = _run_dir(workspaces_root, run_id)
    request = make_request_ir(
        session_id=native, messages=[Message(role="user", content=[TextBlock(text="ask")])]
    )
    entry = make_index_entry(exchange_id=f"{run_id}-ex1", run_id=run_id, provider="codex")
    _write_wire(root, entry, make_artifacts(request, make_response_ir()))

    snapshot = _codex_session_meta(native) + "\n" + _codex_response_item("codex answer") + "\n"
    snapshot_path = DiskStorageLayout(root).transcript_snapshot_path(session_id)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(snapshot, encoding="utf-8")

    rollout = root / "rollout.jsonl"  # the descriptor target — never read by replay (snapshot wins)
    descriptor = encode_source_descriptor(FileTailSource(path=str(rollout), format="codex_rollout"))
    write_owned_session_facts(
        root,
        OwnedSessionFacts(
            run_id=run_id,
            cli="codex",
            native_session_id=native,
            minted=False,
            source_descriptor=descriptor,
        ),
    )
    return session_id


def _seed_claude_run(
    workspaces_root: Path, run_id: str, sid: str, *, write_cli_file: bool = True
) -> tuple[Path, Path]:
    """Seed a complete owned-claude run dir; return ``(root, cli_path)``.

    Wire: one anthropic exchange whose response shares ``"answer"`` with the transcript (so the diff
    has a real ``shared`` bucket — the cross-stream dedup linchpin). Transcript snapshot: a user turn
    (``"hi"`` — transcript_only) + an assistant turn (``"answer"`` — shared). The CLI source file (the
    descriptor target) is written only when *write_cli_file* — the killer demo deletes it.
    """
    root = _run_dir(workspaces_root, run_id)
    request = make_request_ir(
        session_id=sid,
        system=[SystemPart(text="sys")],
        messages=[Message(role="user", content=[TextBlock(text="ask")])],
    )
    entry = make_index_entry(exchange_id=f"{run_id}-ex1", run_id=run_id, provider="anthropic")
    _write_wire(root, entry, make_artifacts(request, make_response_ir()))

    snapshot = _claude_user("u1", "hi", sid) + "\n" + _claude_assistant("a1", "u1", "answer", sid)
    snapshot += "\n"
    snapshot_path = DiskStorageLayout(root).transcript_snapshot_path(sid)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(snapshot, encoding="utf-8")

    cli_path = root / "cli.jsonl"
    if write_cli_file:
        cli_path.write_text(snapshot, encoding="utf-8")
    write_owned_session_facts(
        root,
        OwnedSessionFacts(
            run_id=run_id,
            cli="claude",
            native_session_id=sid,
            minted=True,
            source_descriptor=_descriptor(cli_path),
        ),
    )
    return root, cli_path


def _drain(db_path: Path) -> IndexWriter:
    writer = IndexWriter(str(db_path), flush_ms=5)
    writer.start()
    return writer


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = (
        "session",
        "wire_exchange",
        "transcript_turn",
        "block",
        "exchange_block",
        "turn_block",
    )
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
