"""The launch-side profile port (§5.2c): the single managed-launch entry point claude, codex, and
any future mint-capable CLI share. Mirrors the read-side ``TranscriptAdapter`` (one subclass per CLI)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from transport_matters.cli.launch_profile import (
    PROFILES,
    ClaudeLaunchProfile,
    CodexLaunchProfile,
    LaunchProfile,
    ManagedSession,
    persist_owned_session_facts,
    prepare_managed_session,
)
from transport_matters.index.adapters.base import (
    FileTailSource,
    decode_source_descriptor,
    encode_source_descriptor,
)
from transport_matters.storage.session_facts import read_run_session_facts

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def _now() -> datetime:
    return datetime(2026, 6, 5, 3, 34, 20, 574000, tzinfo=UTC)


class TestClaudeProfile:
    def test_client_argv_injects_session_id_after_passthrough(self) -> None:
        argv = ClaudeLaunchProfile().client_argv(
            client_path="/bin/claude", passthrough=["-p", "hi"], native_session_id="uuid-1"
        )
        assert argv == ["/bin/claude", "-p", "hi", "--session-id", "uuid-1"]

    def test_client_argv_omits_session_when_unowned(self) -> None:
        # External adoption / user passthrough: no owned id → no injection (their flag wins).
        argv = ClaudeLaunchProfile().client_argv(
            client_path="/bin/claude", passthrough=["-p", "hi"], native_session_id=None
        )
        assert argv == ["/bin/claude", "-p", "hi"]

    def test_user_supplied_session_detects_claude_session_flags(self) -> None:
        profile = ClaudeLaunchProfile()
        assert profile.user_supplied_session(["--session-id", "x"]) is True
        assert profile.user_supplied_session(["--resume", "x"]) is True
        assert profile.user_supplied_session(["-r"]) is True
        assert profile.user_supplied_session(["--continue"]) is True
        assert profile.user_supplied_session(["-c"]) is True
        # equals form must be detected too (claude accepts ``--flag=value``)
        assert (
            profile.user_supplied_session(["--session-id=00000000-0000-4000-8000-000000000001"])
            is True
        )
        assert profile.user_supplied_session(["--resume=their-id"]) is True
        assert profile.user_supplied_session(["-p", "hello"]) is False
        assert (
            profile.user_supplied_session(["--model=opus"]) is False
        )  # unrelated =flag, no false positive

    def test_prepare_mints_descriptor_under_home_aware_root_without_seeding(
        self, tmp_path: Path
    ) -> None:
        # claude --session-id CREATES the transcript; prepare writes NOTHING, it only computes the
        # deterministic descriptor under the home-aware projects root (matches where claude writes).
        descriptor = ClaudeLaunchProfile().prepare(
            native_session_id="owned-uuid",
            client_path="/bin/claude",
            working_dir=Path("/Users/x/proj"),
            home_dir=tmp_path,
            env={},
            now=_now(),
            write=True,
        )
        source = decode_source_descriptor(descriptor)
        assert isinstance(source, FileTailSource)
        assert source.format == "claude_jsonl"
        assert source.path == str(tmp_path / "projects" / "-Users-x-proj" / "owned-uuid.jsonl")
        assert source.home_dir == str(tmp_path)  # managed home recorded explicitly (§11.1)
        assert not Path(source.path).exists()  # no seed — claude creates it


class TestCodexProfile:
    def test_client_argv_resumes_owned_rollout(self) -> None:
        argv = CodexLaunchProfile().client_argv(
            client_path="/bin/codex", passthrough=["exec", "ping"], native_session_id="native-9"
        )
        assert argv[0] == "/bin/codex"
        assert argv[1] == "-c"  # the shell-environment-policy arg precedes resume
        resume_at = argv.index("resume")
        assert argv[resume_at + 1] == "native-9"
        assert argv[-2:] == ["exec", "ping"]

    def test_client_argv_omits_resume_when_unowned(self) -> None:
        argv = CodexLaunchProfile().client_argv(
            client_path="/bin/codex", passthrough=["exec", "ping"], native_session_id=None
        )
        assert "resume" not in argv
        assert argv[-2:] == ["exec", "ping"]

    def test_user_supplied_session_detects_resume(self) -> None:
        profile = CodexLaunchProfile()
        assert profile.user_supplied_session(["resume", "abc"]) is True
        assert profile.user_supplied_session(["exec", "ping"]) is False

    def test_prepare_seeds_rollout_under_home_aware_root(self, tmp_path: Path) -> None:
        # codex resume needs the pre-seeded rollout; prepare writes it under the home-aware root.
        descriptor = CodexLaunchProfile().prepare(
            native_session_id="019e0000-0000-7000-8000-00000000c0de",
            client_path="/nonexistent/codex",  # version probe falls back to 0.0.0, never fails
            working_dir=Path("/w"),
            home_dir=tmp_path,
            env={},
            now=_now(),
            write=True,
        )
        source = decode_source_descriptor(descriptor)
        assert isinstance(source, FileTailSource)
        assert source.format == "codex_rollout"
        assert source.path.startswith(str(tmp_path / "sessions"))
        assert source.home_dir == str(tmp_path)  # managed home recorded explicitly (§11.1)
        assert Path(source.path).exists()  # codex needs the seed on disk


class TestPrepareManagedSession:
    def test_mints_uuid_and_prepares_for_a_managed_client(self, tmp_path: Path) -> None:
        session = prepare_managed_session(
            ClaudeLaunchProfile(),
            client_path="/bin/claude",
            passthrough=["-p", "hi"],
            working_dir=Path("/Users/x/proj"),
            home_dir=tmp_path,
            env={},
            now=_now(),
            write=True,
        )
        assert isinstance(session, ManagedSession)
        UUID(session.native_session_id)  # a real uuid4
        source = decode_source_descriptor(session.source_descriptor)
        assert isinstance(source, FileTailSource)
        assert source.path.endswith(f"{session.native_session_id}.jsonl")

    def test_none_when_no_managed_client(self, tmp_path: Path) -> None:
        # proxy-only (--no-claude): nothing to mint for.
        assert (
            prepare_managed_session(
                ClaudeLaunchProfile(),
                client_path=None,
                passthrough=[],
                working_dir=Path("/w"),
                home_dir=tmp_path,
                env={},
                now=_now(),
                write=True,
            )
            is None
        )

    def test_none_when_user_pinned_a_session(self, tmp_path: Path) -> None:
        # Honor user passthrough: their --session-id wins; TM does not mint → external adoption.
        assert (
            prepare_managed_session(
                ClaudeLaunchProfile(),
                client_path="/bin/claude",
                passthrough=["--resume", "their-id"],
                working_dir=Path("/w"),
                home_dir=tmp_path,
                env={},
                now=_now(),
                write=True,
            )
            is None
        )

    def test_none_when_user_pinned_a_session_equals_form(self, tmp_path: Path) -> None:
        # The equals form (``--session-id=<uuid>``) must be honored like the space form: TM mints
        # NOTHING, so no second --session-id is injected and no owned descriptor is recorded.
        assert (
            prepare_managed_session(
                ClaudeLaunchProfile(),
                client_path="/bin/claude",
                passthrough=["--session-id=00000000-0000-4000-8000-000000000001"],
                working_dir=Path("/w"),
                home_dir=tmp_path,
                env={},
                now=_now(),
                write=True,
            )
            is None
        )

    def test_write_false_skips_codex_seed_but_still_describes(self, tmp_path: Path) -> None:
        # print-command dry run must not touch disk, yet still computes the descriptor.
        session = prepare_managed_session(
            CodexLaunchProfile(),
            client_path="/nonexistent/codex",
            passthrough=["exec", "ping"],
            working_dir=Path("/w"),
            home_dir=tmp_path,
            env={},
            now=_now(),
            write=False,
        )
        assert session is not None
        source = decode_source_descriptor(session.source_descriptor)
        assert isinstance(source, FileTailSource)
        assert not Path(source.path).exists()


def test_registry_maps_each_cli_to_its_profile() -> None:
    assert isinstance(PROFILES["claude"], ClaudeLaunchProfile)
    assert isinstance(PROFILES["codex"], CodexLaunchProfile)
    # every registered profile is keyed by its own declared cli (no drift)
    assert all(cli == profile.cli for cli, profile in PROFILES.items())


class _FakeMintProfile(LaunchProfile):
    """A hypothetical third mint-capable CLI — implemented as ONE small profile, nothing else."""

    cli = "fakecli"
    mints_session_id = False

    def prepare(
        self,
        *,
        native_session_id: str,
        client_path: str,
        working_dir: Path,
        home_dir: Path | None,
        env: Mapping[str, str],
        now: datetime,
        write: bool,
    ) -> str:
        return encode_source_descriptor(
            FileTailSource(path=f"/fake/{native_session_id}.log", format="fake_log")
        )

    def client_argv(
        self, *, client_path: str, passthrough: Sequence[str], native_session_id: str | None
    ) -> list[str]:
        session = [] if native_session_id is None else [f"--id={native_session_id}"]
        return [client_path, *session, *passthrough]

    def user_supplied_session(self, passthrough: Sequence[str]) -> bool:
        return any(arg.startswith("--id") for arg in passthrough)


def test_dry_a_new_mint_capable_cli_plugs_into_the_shared_path(tmp_path: Path) -> None:
    # Regression (e): adding a mint-capable CLI is "implement one profile". The SHARED
    # prepare_managed_session mints + prepares it with ZERO edits to the launch flow.
    session = prepare_managed_session(
        _FakeMintProfile(),
        client_path="/bin/fake",
        passthrough=["hi"],
        working_dir=Path("/w"),
        home_dir=None,
        env={},
        now=_now(),
        write=True,
    )
    assert session is not None
    UUID(session.native_session_id)
    source = decode_source_descriptor(session.source_descriptor)
    assert isinstance(source, FileTailSource)
    assert source.path == f"/fake/{session.native_session_id}.log"
    argv = _FakeMintProfile().client_argv(
        client_path="/bin/fake", passthrough=["hi"], native_session_id=session.native_session_id
    )
    assert argv == ["/bin/fake", f"--id={session.native_session_id}", "hi"]


class TestPersistOwnedSessionFacts:
    def test_mints_session_id_matches_bind_exchange_per_cli(self) -> None:
        # The launch-side declaration must agree with bind_exchange's read-side derivation: claude
        # adopts the injected --session-id as its PK (minted), codex synthesizes the PK (not minted).
        assert ClaudeLaunchProfile().mints_session_id is True
        assert CodexLaunchProfile().mints_session_id is False

    def test_writes_durable_facts_from_profile_and_managed_session(self, tmp_path: Path) -> None:
        # §11.1: the launcher persists the owned facts once, sourcing cli + minted from the profile and
        # native id + descriptor from the ManagedSession, under the run dir (== storage_root).
        descriptor = encode_source_descriptor(
            FileTailSource(path="/p", format="claude_jsonl", home_dir=str(tmp_path))
        )
        managed = ManagedSession(native_session_id="owned-uuid", source_descriptor=descriptor)
        path = persist_owned_session_facts(
            ClaudeLaunchProfile(),
            managed,
            run_id="run-1",
            storage_root=tmp_path,
            home_dir=tmp_path,
        )
        assert path == tmp_path / "sessions.json"
        facts = read_run_session_facts(tmp_path)
        assert facts is not None
        (owned,) = facts.sessions
        assert owned.run_id == "run-1"
        assert owned.cli == "claude"
        assert owned.native_session_id == "owned-uuid"
        assert owned.minted is True
        assert owned.source_descriptor == descriptor
        assert owned.home_dir == str(tmp_path)

    def test_native_home_records_none(self, tmp_path: Path) -> None:
        descriptor = encode_source_descriptor(FileTailSource(path="/p", format="codex_rollout"))
        managed = ManagedSession(native_session_id="native-1", source_descriptor=descriptor)
        persist_owned_session_facts(
            CodexLaunchProfile(), managed, run_id="run-1", storage_root=tmp_path, home_dir=None
        )
        facts = read_run_session_facts(tmp_path)
        assert facts is not None
        assert facts.sessions[0].minted is False  # codex synth PK
        assert facts.sessions[0].home_dir is None
