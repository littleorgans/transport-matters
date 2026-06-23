"""Tests for the transcript denylist reader."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from transport_matters.transcript_denylist import TranscriptDenyRule, read_transcript_denylist

if TYPE_CHECKING:
    from pathlib import Path


def test_missing_file_defaults_empty(tmp_path: Path) -> None:
    # A missing file is the default state, not an error: reveal everything.
    assert read_transcript_denylist(tmp_path).hide == ()


def test_parses_hide_rules(tmp_path: Path) -> None:
    (tmp_path / "transcript_denylist.json").write_text(
        json.dumps({"hide": [{"path": "type", "equals": "user"}, {"path": "attachment.type"}]}),
        encoding="utf-8",
    )
    denylist = read_transcript_denylist(tmp_path)
    assert denylist.hide == (
        TranscriptDenyRule(path="type", equals="user"),
        TranscriptDenyRule(path="attachment.type"),
    )


def test_malformed_json_defaults_empty(tmp_path: Path) -> None:
    # A typo must never blank the transcript view: fall back to empty.
    (tmp_path / "transcript_denylist.json").write_text("{not json", encoding="utf-8")
    assert read_transcript_denylist(tmp_path).hide == ()


def test_invalid_schema_defaults_empty(tmp_path: Path) -> None:
    # A bare list (missing the ``hide`` wrapper) is rejected and treated as empty.
    (tmp_path / "transcript_denylist.json").write_text(
        json.dumps([{"path": "type"}]), encoding="utf-8"
    )
    assert read_transcript_denylist(tmp_path).hide == ()
