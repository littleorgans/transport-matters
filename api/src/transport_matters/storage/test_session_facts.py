"""Durable per-run owned-launch facts (§11.1): write/read round-trip, upsert, dir creation."""

from typing import TYPE_CHECKING

from transport_matters.storage.session_facts import (
    OwnedSessionFacts,
    read_run_session_facts,
    write_owned_session_facts,
)

if TYPE_CHECKING:
    from pathlib import Path

_DESCRIPTOR = (
    '{"kind":"file_tail","path":"/p","format":"claude_jsonl","home_dir":"/managed/.claude"}'
)


def _facts(
    native: str = "native-1", *, home_dir: str | None = "/managed/.claude"
) -> OwnedSessionFacts:
    return OwnedSessionFacts(
        run_id="run-1",
        harness="claude",
        native_session_id=native,
        minted=True,
        source_descriptor=_DESCRIPTOR,
        home_dir=home_dir,
    )


class TestWriteRead:
    def test_round_trips_owned_facts(self, tmp_path: Path) -> None:
        path = write_owned_session_facts(tmp_path, _facts())
        assert path == tmp_path / "sessions.json"
        facts = read_run_session_facts(tmp_path)
        assert facts is not None
        (owned,) = facts.sessions
        assert owned == _facts()
        assert list(tmp_path.glob("*.tmp")) == []  # atomic write leaves no temp file

    def test_read_missing_returns_none(self, tmp_path: Path) -> None:
        # A run with no owned session (proxy-only / external adoption) or a pre-8b-ii dir.
        assert read_run_session_facts(tmp_path) is None

    def test_home_dir_none_persists(self, tmp_path: Path) -> None:
        write_owned_session_facts(tmp_path, _facts(home_dir=None))
        facts = read_run_session_facts(tmp_path)
        assert facts is not None
        assert facts.sessions[0].home_dir is None

    def test_creates_dir_when_absent(self, tmp_path: Path) -> None:
        # An explicit --storage-dir may not exist yet (the per-run lock creates the default run dir).
        target = tmp_path / "nested" / "run"
        write_owned_session_facts(target, _facts())
        assert (target / "sessions.json").is_file()


class TestUpsert:
    def test_same_native_id_replaces_not_appends(self, tmp_path: Path) -> None:
        # Idempotent on the owning native id: a re-write replaces the entry (latest wins), never dups.
        write_owned_session_facts(tmp_path, _facts("native-1", home_dir="/a"))
        write_owned_session_facts(tmp_path, _facts("native-1", home_dir="/b"))
        facts = read_run_session_facts(tmp_path)
        assert facts is not None
        (owned,) = facts.sessions
        assert owned.home_dir == "/b"

    def test_distinct_native_ids_accumulate(self, tmp_path: Path) -> None:
        # A run dir may host more than one owned session (the transcript-snapshot granularity).
        write_owned_session_facts(tmp_path, _facts("native-1"))
        write_owned_session_facts(tmp_path, _facts("native-2"))
        facts = read_run_session_facts(tmp_path)
        assert facts is not None
        assert {s.native_session_id for s in facts.sessions} == {"native-1", "native-2"}
