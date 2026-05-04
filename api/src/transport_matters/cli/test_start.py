"""Cross-cutting tests for ``transport-matters claude``.

Focused section files cover print-command, pass-through handling,
validation, child wiring, workspace locking, and storage propagation.
This module keeps only the smaller integration-style checks that still
exercise the command surface end to end.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from typer.testing import CliRunner

from transport_matters.cli import main

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

runner = CliRunner()


def test_start_accepts_directory_argument(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """A valid directory passes validation and reaches print-command."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which", lambda name, path=None: f"/bin/{name}"
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(main, ["claude", str(workdir), "--print-command"])
    assert result.exit_code == 0


def test_start_does_not_pollute_os_environ(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """The start command builds a child_env dict instead of mutating os.environ."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which", lambda name, path=None: f"/bin/{name}"
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)
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
    spy_run_children: MagicMock,
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
    spy_run_children.assert_not_called()
