"""Managed-mint acceptance for ``transport-matters claude`` (§5.2c): own the session id at launch.

Mirrors ``test_codex.py::test_codex_managed_mint_seeds_rollout_and_resumes`` on the launch side."""

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from typer.testing import CliRunner

from transport_matters.cli import main
from transport_matters.index.adapters.base import FileTailSource, decode_source_descriptor

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
