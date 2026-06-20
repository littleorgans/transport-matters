"""Phase 2 acceptance tests for ``manicure start``.

Exercises the product-level features that landed alongside the
``cli/`` decomposition: deterministic channel ports and automatic
``--append-system-prompt`` injection. Kept separate from ``test_start.py``
so the bulk start surface stays under the per-file LOC budget.
"""

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from transport_matters.cli import main

from ._helpers import _which_all, _which_by_name

if TYPE_CHECKING:
    from pathlib import Path
    from unittest.mock import MagicMock

runner = CliRunner()


# --------------------------------------------------------------------------- #
# start: channel port defaults                                                #
# --------------------------------------------------------------------------- #


def test_start_channel_default_ports_appear_in_print_command(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)

    result = runner.invoke(main, ["claude", "--print-command"])

    assert result.exit_code == 0, result.output
    assert "--listen-port 8787" in result.stdout
    assert "http://127.0.0.1:8788" in result.stdout
    spy_run_client_children.assert_not_called()


def test_start_explicit_proxy_port_keeps_channel_web_default(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)

    result = runner.invoke(
        main,
        ["claude", "--proxy-port", "9000", "--print-command"],
    )

    assert result.exit_code == 0, result.output
    assert "--listen-port 9000" in result.stdout
    assert "http://127.0.0.1:8788" in result.stdout
    spy_run_client_children.assert_not_called()


@pytest.mark.parametrize("bad_port", ["0", "-1", "65536", "99999"])
def test_start_rejects_out_of_range_port_values(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
    bad_port: str,
) -> None:
    """Typer's port callback must reject 0 (silent skip), negatives, and
    >65535 *before* we hand anything to mitmdump or the kernel. Caught at
    parse time, click exits with code 2 and a "Invalid value" frame."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    result = runner.invoke(
        main, ["claude", "--proxy-port", bad_port, "--no-claude", "--print-command"]
    )
    assert result.exit_code == 2
    # Click prints "Invalid value for '--proxy-port' / '-p': port must be in 1..65535, got <bad_port>."
    assert "1..65535" in result.output
    assert bad_port in result.output
    assert "Omit the flag" in result.output
    spy_run_client_children.assert_not_called()


# --------------------------------------------------------------------------- #
# start: system-prompt injection                                              #
# --------------------------------------------------------------------------- #


def test_start_injects_system_prompt_by_default(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """Default behaviour: prepend ``--append-system-prompt`` with the
    proxy + inspector URLs so the model knows it is inside transport_matters."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)

    result = runner.invoke(main, ["claude", "--proxy-port", "9000", "--web-port", "9001"])
    assert result.exit_code == 0, result.output
    argv = spy_run_client_children.call_args.kwargs["client"].argv
    # client.argv = [claude_path, *passthrough]; injection prepends
    # `--append-system-prompt <text>` to the passthrough, so the binary
    # stays at index 0 with the injection following.
    assert argv[0] == "/bin/claude"
    assert argv[1] == "--append-system-prompt"
    prompt = argv[2]
    assert "http://127.0.0.1:9000" in prompt
    assert "http://127.0.0.1:9001" in prompt


def test_start_no_system_prompt_skips_injection(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """``--no-system-prompt`` short-circuits the auto-injection branch."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)

    result = runner.invoke(main, ["claude", "--no-system-prompt"])
    assert result.exit_code == 0, result.output
    argv = spy_run_client_children.call_args.kwargs["client"].argv
    assert "--append-system-prompt" not in argv
    # no system prompt injected; claude still mints its owned --session-id by default (§5.2c)
    assert argv[0] == "/bin/claude"
    assert argv[-2] == "--session-id"


def test_start_user_supplied_system_prompt_wins(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """If the user passes their own ``--system-prompt`` (or
    ``--append-system-prompt``) after ``--``, manicure must NOT also
    inject — the user's prompt wins."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)

    result = runner.invoke(main, ["claude", "--", "--system-prompt", "you are X"])
    assert result.exit_code == 0, result.output
    argv = spy_run_client_children.call_args.kwargs["client"].argv
    # Exactly one --system-prompt (the user's) and zero
    # --append-system-prompt (manicure stayed out of it).
    assert argv.count("--system-prompt") == 1
    assert "--append-system-prompt" not in argv
    # User's prompt token survives intact.
    assert "you are X" in argv


def test_start_user_supplied_append_system_prompt_wins(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """Same as above for ``--append-system-prompt`` — manicure detects
    either flag and stays out of the way."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli.port_in_use", lambda _: False)

    result = runner.invoke(
        main,
        ["claude", "--proxy-port", "9000", "--", "--append-system-prompt", "extra"],
    )
    assert result.exit_code == 0, result.output
    argv = spy_run_client_children.call_args.kwargs["client"].argv
    # Only the user's --append-system-prompt is present (manicure's
    # injection would have added a second).
    assert argv.count("--append-system-prompt") == 1
    # And manicure's URL is NOT in the prompt — only the user's "extra".
    assert "extra" in argv
    assert not any("http://localhost:9000" in tok for tok in argv)
    assert not any("http://127.0.0.1:9000" in tok for tok in argv)
