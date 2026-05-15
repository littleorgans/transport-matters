from __future__ import annotations

from typing import TYPE_CHECKING

from typer.testing import CliRunner

from transport_matters.cli import main

from ._helpers import _which_all, _which_by_name

if TYPE_CHECKING:
    from pathlib import Path
    from unittest.mock import MagicMock

    import pytest

runner = CliRunner()


def test_start_calls_run_client_children_with_claude_client(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """When not using --print-command, the shared runner gets a Claude client."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(
        main,
        ["claude", str(workdir), "--no-system-prompt", "--proxy-port", "9900"],
    )
    assert result.exit_code == 0, result.output
    spy_run_client_children.assert_called_once()
    kwargs = spy_run_client_children.call_args.kwargs
    client = kwargs["client"]
    assert client.name == "claude"
    assert client.display_name == "Claude"
    assert client.argv == ["/bin/claude"]
    assert client.env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9900"
    assert client.cwd == workdir
    assert kwargs["proxy_port"] == 9900
    assert f"TRANSPORT_MATTERS_CWD={workdir}" in result.output
    assert kwargs["mitmdump_argv"][0] == "/bin/mitmdump"
    assert "reverse:https://api.anthropic.com" in kwargs["mitmdump_argv"]


def test_start_sanitizes_managed_claude_env(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)
    monkeypatch.setenv("HTTP_PROXY", "http://corp-proxy:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://corp-proxy:8080")
    monkeypatch.setenv("ALL_PROXY", "socks5://corp-proxy:1080")
    monkeypatch.setenv("NO_PROXY", "internal.example")
    monkeypatch.setenv("SSL_CERT_FILE", "/tmp/custom.pem")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/tmp/requests.pem")
    monkeypatch.setenv("NODE_EXTRA_CA_CERTS", "/tmp/node-extra.pem")
    monkeypatch.setenv("NODE_TLS_REJECT_UNAUTHORIZED", "0")

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(
        main,
        ["claude", str(workdir), "--no-system-prompt", "--proxy-port", "9900"],
    )
    assert result.exit_code == 0, result.output

    claude_env = spy_run_client_children.call_args.kwargs["client"].env
    assert claude_env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9900"
    assert claude_env["NO_PROXY"] == "127.0.0.1,localhost"
    assert claude_env["no_proxy"] == "127.0.0.1,localhost"
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
        "NODE_EXTRA_CA_CERTS",
        "NODE_TLS_REJECT_UNAUTHORIZED",
    ):
        assert key not in claude_env


def test_start_no_claude_passes_none_client(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    result = runner.invoke(main, ["claude", "--no-claude"])
    assert result.exit_code == 0, result.output
    kwargs = spy_run_client_children.call_args.kwargs
    assert kwargs["client"] is None
