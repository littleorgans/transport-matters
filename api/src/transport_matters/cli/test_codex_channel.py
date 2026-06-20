"""Tests for the `manicure codex --channel` launch path."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from typer.testing import CliRunner

from transport_matters import env_keys
from transport_matters.cli import BindFailure, main

from ._helpers import _which_by_name

if TYPE_CHECKING:
    from pathlib import Path
    from unittest.mock import MagicMock

    import pytest

runner = CliRunner()


def test_codex_channel_flag_uses_preview_defaults(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    monkeypatch.delenv(env_keys.CHANNEL, raising=False)

    result = runner.invoke(
        main,
        ["codex", "--channel", "preview", "--no-codex", "--print-command"],
    )

    assert result.exit_code == 0, result.output
    assert "--listen-port 8797" in result.stdout
    assert os.environ[env_keys.CHANNEL] == "preview"


def test_codex_channel_env_reaches_launch_environment(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)

    result = runner.invoke(main, ["codex", "--channel", "preview", "--no-codex"])

    assert result.exit_code == 0, result.output
    kwargs = spy_run_client_children.call_args.kwargs
    assert kwargs["proxy_port"] == 8797
    assert kwargs["web_port"] == 8798
    assert kwargs["mitmdump_env"][env_keys.CHANNEL] == "preview"


def test_codex_channel_default_bind_failure_fails_without_reallocation(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "codex": "/bin/codex"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)
    bundle_path = tmp_path / "ca.pem"
    bundle_path.write_text("bundle", encoding="utf-8")
    monkeypatch.setattr(
        "transport_matters.cli.resolve_codex_ca_certificate",
        lambda *, env, bundle_dir: bundle_path,
    )
    log_path = tmp_path / "mitmdump.log"

    def _side_effect(**kwargs: Any) -> None:
        raise BindFailure(
            proxy_port=kwargs["proxy_port"],
            web_port=kwargs["web_port"],
            failing_ports=(8797,),
            log_path=log_path,
        )

    spy_run_client_children.side_effect = _side_effect

    result = runner.invoke(main, ["codex", "--channel", "preview", "--no-codex"])

    assert result.exit_code == 2
    assert "pinned port in use: --proxy-port 8797" in result.output
    assert spy_run_client_children.call_count == 1
