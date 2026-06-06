"""Shared tier-1 run-dir seeders for transcript replay tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from transport_matters.index.adapters.base import FileTailSource, encode_source_descriptor
from transport_matters.index.sessions import synth_session_id
from transport_matters.storage.disk_layout import DiskStorageLayout
from transport_matters.storage.session_facts import OwnedSessionFacts, write_owned_session_facts

if TYPE_CHECKING:
    from pathlib import Path

_SLUG = "proj"
_HASH = "h1"


def _run_dir(workspaces_root: Path, run_id: str) -> Path:
    root = workspaces_root / _SLUG / _HASH / run_id
    root.mkdir(parents=True)
    (root / "index.jsonl").touch()
    return root


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


def _claude_descriptor(path: Path) -> str:
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
    """Seed an owned Codex run and return the synthesized session id."""
    session_id = synth_session_id(run_id, "codex", native)
    root = _run_dir(workspaces_root, run_id)

    snapshot = _codex_session_meta(native) + "\n" + _codex_response_item("codex answer") + "\n"
    snapshot_path = DiskStorageLayout(root).transcript_snapshot_path(session_id)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(snapshot, encoding="utf-8")

    rollout = root / "rollout.jsonl"
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
    """Seed a complete owned Claude run dir and return ``(root, cli_path)``."""
    root = _run_dir(workspaces_root, run_id)
    snapshot = _claude_user("u1", "hi", sid) + "\n"
    snapshot += _claude_assistant("a1", "u1", "answer", sid) + "\n"
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
            source_descriptor=_claude_descriptor(cli_path),
        ),
    )
    return root, cli_path
