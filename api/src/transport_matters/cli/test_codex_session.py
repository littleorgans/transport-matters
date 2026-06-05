"""Managed-mint launch seam for codex (§5.2b): rollout path, session_meta seed, version resolve."""

import json
from datetime import UTC, datetime
from pathlib import Path

from transport_matters.cli.codex_session import (
    CodexSessionSeed,
    build_session_meta,
    codex_rollout_path,
    resolve_codex_cli_version,
    seed_codex_session,
)
from transport_matters.index.adapters.base import FileTailSource, decode_source_descriptor

_NATIVE = "019e0000-0000-7000-8000-00000000abcd"


def _now() -> datetime:
    return datetime(2026, 6, 5, 3, 34, 20, 574000, tzinfo=UTC)


class TestRolloutPath:
    def test_layout_matches_codex_convention(self, tmp_path: Path) -> None:
        # codex stores rollouts at <home>/sessions/YYYY/MM/DD/rollout-<wallclock>-<uuid>.jsonl.
        path = codex_rollout_path(_NATIVE, _now(), sessions_root=tmp_path)
        assert path.parent == tmp_path / "2026" / "06" / "05"
        assert path.name == f"rollout-2026-06-05T03-34-20-{_NATIVE}.jsonl"


class TestSessionMeta:
    def test_minimal_record_has_resume_fields(self) -> None:
        # The minimal record `codex resume <uuid>` accepts: payload.{id,timestamp,cwd,originator,
        # cli_version} (verified on real rollouts). The native uuid is what resume keys on.
        record = build_session_meta(_NATIVE, _now(), "/w", "0.137.0")
        assert record["type"] == "session_meta"
        payload = record["payload"]
        assert payload["id"] == _NATIVE
        assert payload["cwd"] == "/w"
        assert payload["originator"] == "codex-tui"
        assert payload["cli_version"] == "0.137.0"
        assert payload["timestamp"] == "2026-06-05T03:34:20.574Z"  # UTC, ms precision, Z
        assert record["timestamp"] == payload["timestamp"]


class TestSeed:
    def test_seed_writes_rollout_and_returns_owned_descriptor(self, tmp_path: Path) -> None:
        seed = seed_codex_session(
            native_session_id=_NATIVE,
            now=_now(),
            working_dir=Path("/w"),
            cli_version="0.137.0",
            sessions_root=tmp_path,
        )
        assert isinstance(seed, CodexSessionSeed)
        assert seed.native_session_id == _NATIVE
        # the descriptor points the tailer at the EXACT owned path (no glob)
        source = decode_source_descriptor(seed.source_descriptor)
        assert isinstance(source, FileTailSource)
        assert source.format == "codex_rollout"
        path = codex_rollout_path(_NATIVE, _now(), sessions_root=tmp_path)
        assert source.path == str(path)
        # the file exists, holds exactly the session_meta seed, and is newline-terminated (tailer-safe)
        text = path.read_text(encoding="utf-8")
        assert text.endswith("\n")
        (line,) = text.splitlines()
        assert json.loads(line)["payload"]["id"] == _NATIVE

    def test_write_false_skips_the_file_but_still_describes_it(self, tmp_path: Path) -> None:
        # print-command (dry run) must not touch the filesystem, yet the printed argv still needs the
        # descriptor/path it WOULD own.
        seed = seed_codex_session(
            native_session_id=_NATIVE,
            now=_now(),
            working_dir=Path("/w"),
            cli_version="0.137.0",
            sessions_root=tmp_path,
            write=False,
        )
        path = codex_rollout_path(_NATIVE, _now(), sessions_root=tmp_path)
        assert not path.exists()
        described = decode_source_descriptor(seed.source_descriptor)
        assert isinstance(described, FileTailSource)
        assert described.path == str(path)


class TestVersionResolve:
    def test_parses_trailing_semver_from_version_output(self) -> None:
        def fake_run(*_args: object, **_kwargs: object) -> object:
            return type("R", (), {"stdout": "codex-cli 0.137.0\n"})()

        assert resolve_codex_cli_version("/bin/codex", run=fake_run) == "0.137.0"

    def test_falls_back_when_binary_unavailable(self) -> None:
        def boom(*_args: object, **_kwargs: object) -> object:
            raise FileNotFoundError("/bin/codex")

        # a missing/odd binary must not crash the launch — best-effort version.
        assert resolve_codex_cli_version("/bin/codex", run=boom) == "0.0.0"
