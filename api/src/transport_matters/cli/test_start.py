"""Cross-cutting tests for ``transport-matters claude``.

Focused section files cover print-command, pass-through handling,
validation, child wiring, workspace locking, and storage propagation.
This module keeps only the smaller integration-style checks that still
exercise the command surface end to end.
"""

import os
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from typer.testing import CliRunner

from transport_matters import env_keys
from transport_matters.cli import main

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

runner = CliRunner()


def test_start_accepts_work_dir_option(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """A valid --work-dir path reaches print-command."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which", lambda name, path=None: f"/bin/{name}"
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(main, ["claude", "--work-dir", str(workdir), "--print-command"])
    assert result.exit_code == 0


def test_start_channel_flag_activates_preview_defaults(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """``--channel preview`` pins the preview channel and deterministic ports."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which", lambda name, path=None: f"/bin/{name}"
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.delenv(env_keys.CHANNEL, raising=False)

    result = runner.invoke(main, ["claude", "--channel", "preview", "--print-command"])

    assert result.exit_code == 0, result.output
    assert os.environ[env_keys.CHANNEL] == "preview"
    assert "--listen-port 8797" in result.stdout
    assert "8798" in result.stdout
    spy_run_client_children.assert_not_called()


def test_start_channel_env_activates_preview_defaults(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which", lambda name, path=None: f"/bin/{name}"
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)

    result = runner.invoke(
        main,
        ["claude", "--print-command"],
        env={env_keys.CHANNEL: "preview"},
    )

    assert result.exit_code == 0, result.output
    assert "--listen-port 8797" in result.stdout
    spy_run_client_children.assert_not_called()


def test_start_channel_env_reaches_launch_environment(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """The active channel reaches the addon environment."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        lambda name, path=None: "/bin/mitmdump" if name == "mitmdump" else None,
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)

    result = runner.invoke(main, ["claude", "--channel", "preview", "--no-claude"])

    assert result.exit_code == 0, result.output
    kwargs = spy_run_client_children.call_args.kwargs
    assert kwargs["proxy_port"] == 8797
    assert kwargs["web_port"] == 8798
    assert kwargs["mitmdump_env"][env_keys.CHANNEL] == "preview"


def test_start_unknown_channel_exits_with_list_hint(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which", lambda name, path=None: f"/bin/{name}"
    )

    result = runner.invoke(main, ["claude", "--channel", "ghost", "--print-command"])

    assert result.exit_code == 2
    assert "unknown channel 'ghost'" in result.output
    assert "transport-matters channel list" in result.output
    spy_run_client_children.assert_not_called()


def test_start_channel_default_port_in_use_fails_fast(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which", lambda name, path=None: f"/bin/{name}"
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda port: port == 8797)

    result = runner.invoke(main, ["claude", "--channel", "preview", "--print-command"])

    assert result.exit_code == 2
    assert "proxy port 8797 is already in use" in result.output
    spy_run_client_children.assert_not_called()


def test_start_does_not_pollute_os_environ(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """The start command builds a child_env dict instead of mutating os.environ."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which", lambda name, path=None: f"/bin/{name}"
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.delenv("TRANSPORT_MATTERS_WEB_PORT", raising=False)
    monkeypatch.delenv("TRANSPORT_MATTERS_PROXY_PORT", raising=False)

    result = runner.invoke(
        main,
        [
            "claude",
            "--proxy-port",
            "9500",
            "--web-port",
            "9501",
            "--print-command",
        ],
    )
    assert result.exit_code == 0
    assert os.environ.get("TRANSPORT_MATTERS_WEB_PORT") != "9501"
    assert os.environ.get("TRANSPORT_MATTERS_PROXY_PORT") != "9500"


def test_start_fails_when_addon_missing(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    fake_traversable = MagicMock()
    fake_traversable.is_file.return_value = False

    def _fake_files(_pkg: str) -> Any:
        root = MagicMock()
        root.__truediv__.return_value = fake_traversable
        return root

    monkeypatch.setattr("transport_matters.cli.files", _fake_files)

    result = runner.invoke(main, ["claude", "--print-command"])
    assert result.exit_code == 2
    assert "could not locate the Transport Matters mitmproxy addon" in result.output
    spy_run_client_children.assert_not_called()
