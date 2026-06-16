"""Managed-mint acceptance for ``transport-matters claude`` (§5.2c): own the session id at launch.

Mirrors ``test_codex.py::test_codex_managed_mint_seeds_rollout_and_resumes`` on the launch side."""

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from typer.testing import CliRunner

from transport_matters.cli import main
from transport_matters.index.adapters.base import FileTailSource, decode_source_descriptor
from transport_matters.storage.session_facts import read_run_session_facts
from transport_matters.workspace import workspace_root

from ._helpers import _which_by_name

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    import pytest

runner = CliRunner()


def test_claude_managed_mint_injects_session_id_and_owns_descriptor(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    # The launcher mints the native uuid, injects `claude --session-id <uuid>` so claude ADOPTS the
    # owned id (and writes it to the wire), computes the deterministic transcript descriptor (NO seed
    # — claude --session-id CREATES it), and hands the addon the owned native id + descriptor via env.
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)

    result = runner.invoke(main, ["claude", "--no-system-prompt"])
    assert result.exit_code == 0, result.output

    kwargs = spy_run_client_children.call_args.kwargs
    env = kwargs["mitmdump_env"]
    client = kwargs["client"]

    # the addon learns the owned claude identity through the SAME provider-neutral env contract codex uses
    assert env["TRANSPORT_MATTERS_CLI"] == "claude"
    native = env["TRANSPORT_MATTERS_OWNED_NATIVE_SESSION_ID"]
    UUID(native)  # a real uuid4 TM owns
    source = decode_source_descriptor(env["TRANSPORT_MATTERS_OWNED_SOURCE_DESCRIPTOR"])
    assert isinstance(source, FileTailSource)
    assert source.format == "claude_jsonl"
    assert Path(source.path).name == f"{native}.jsonl"  # deterministic path keyed on the owned uuid

    # claude is launched to ADOPT the owned id (--session-id appended; binary stays at argv[0])
    assert client.argv[0] == "/bin/claude"
    assert client.argv[-2:] == ["--session-id", native]

    # NO seed: unlike codex, claude --session-id creates the transcript, so prepare touched no disk
    assert not Path(source.path).exists()


def test_claude_managed_mint_writes_durable_session_facts_under_home_dir(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    # §11.1 durable owned-launch facts: under --agent-home-dir the descriptor records the launched
    # overlay home AND <run_dir>/sessions.json carries the owned facts (native id, descriptor incl.
    # home_dir, cli, minted) so a §10.5 rebuild reads owned state WITHOUT the live env. The home
    # reaches the addon via the OWNED_* env channel (AGENT_HOME_DIR), not only the manifest.
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.chdir(tmp_path)
    workdir = tmp_path / "project"
    workdir.mkdir()

    result = runner.invoke(
        main,
        [
            "claude",
            "--work-dir",
            str(workdir),
            "--agent-home-dir",
            "homes/claude",
            "--no-system-prompt",
        ],
    )
    assert result.exit_code == 0, result.output
    env = spy_run_client_children.call_args.kwargs["mitmdump_env"]
    native = env["TRANSPORT_MATTERS_OWNED_NATIVE_SESSION_ID"]
    storage_dir = Path(env["TRANSPORT_MATTERS_STORAGE_DIR"])
    expected_home = storage_dir / "runtime-home" / "claude"
    # the launched home reaches the addon via the env channel
    assert env["TRANSPORT_MATTERS_AGENT_HOME_DIR"] == str(expected_home)
    # the owned descriptor records the home explicitly and the path resolves under it
    source = decode_source_descriptor(env["TRANSPORT_MATTERS_OWNED_SOURCE_DESCRIPTOR"])
    assert isinstance(source, FileTailSource)
    assert source.home_dir == str(expected_home)
    assert source.path.startswith(str(expected_home / "projects"))

    # durable sessions.json beside index.jsonl in the run dir, readable after the launch returns
    run_dir = workspace_root(workdir) / env["TRANSPORT_MATTERS_RUN_ID"]
    facts = read_run_session_facts(run_dir)
    assert facts is not None
    (owned,) = facts.sessions
    assert owned.native_session_id == native
    assert owned.cli == "claude"
    assert owned.minted is True  # claude adopts the injected --session-id as its session_id PK
    assert owned.home_dir == str(expected_home)
    assert owned.source_descriptor == env["TRANSPORT_MATTERS_OWNED_SOURCE_DESCRIPTOR"]


def test_claude_user_supplied_session_skips_mint(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    # Honor user passthrough: a user-pinned --resume wins — TM does not mint or inject --session-id,
    # and emits no owned id/descriptor (external adoption: the read side falls back to locate).
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)

    result = runner.invoke(
        main, ["claude", "--no-system-prompt", "--", "--resume", "their-session"]
    )
    assert result.exit_code == 0, result.output

    kwargs = spy_run_client_children.call_args.kwargs
    env = kwargs["mitmdump_env"]
    client = kwargs["client"]

    assert "--session-id" not in client.argv  # TM did not inject
    assert client.argv[-2:] == ["--resume", "their-session"]  # the user's flag is preserved
    assert "TRANSPORT_MATTERS_OWNED_NATIVE_SESSION_ID" not in env
    assert "TRANSPORT_MATTERS_OWNED_SOURCE_DESCRIPTOR" not in env
