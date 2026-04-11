"""Tests for the manicure command-line interface.

These cover the four commands end to end via `CliRunner`, plus the
non-trivial helpers. The `start` command shells out via `os.execvpe`,
so we exercise the path up to (but not through) that call — the
`--print-command` flag exits before the exec boundary, which gives us
a clean seam.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from manicure import __version__
from manicure.cli import _port_in_use, main

if TYPE_CHECKING:
    from collections.abc import Iterator

runner = CliRunner()


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable rich color output globally in tests.

    Typer builds its own `rich.Console` per command, which honours
    `NO_COLOR` (and ignores Click's `CliRunner(color=False)`). Without
    this, CI and any shell with `FORCE_COLOR=1` produce help text with
    ANSI escapes interleaved between `-` characters, breaking plain
    substring assertions like `"--json" in result.output`.
    """
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)


@pytest.fixture
def free_port() -> Iterator[int]:
    """Grab an OS-assigned free port, then immediately release it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    yield port


@pytest.fixture
def busy_port() -> Iterator[int]:
    """Bind a port for the duration of the test and yield it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        yield sock.getsockname()[1]


@pytest.fixture
def tmp_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the default storage directory to a temp path for tests."""
    storage = tmp_path / "manicure-home"
    monkeypatch.setenv("MANICURE_STORAGE_DIR", str(storage))
    monkeypatch.delenv("MANICURE_DEBUG", raising=False)
    # Bust the cached settings so the override actually takes effect.
    from manicure import config

    config.get_settings.cache_clear()
    return storage


# --------------------------------------------------------------------------- #
# version / --version                                                         #
# --------------------------------------------------------------------------- #


def test_version_command_prints_version() -> None:
    result = runner.invoke(main, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_version_flag_on_root_prints_version() -> None:
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_version_short_flag_prints_version() -> None:
    result = runner.invoke(main, ["-V"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


# --------------------------------------------------------------------------- #
# paths                                                                       #
# --------------------------------------------------------------------------- #


def test_paths_text_output_lists_expected_keys(tmp_storage: Path) -> None:
    result = runner.invoke(main, ["paths"])
    assert result.exit_code == 0
    for key in ("version", "package", "addon", "www", "storage", "rules"):
        assert key in result.stdout


def test_paths_json_is_valid_and_structured(tmp_storage: Path) -> None:
    result = runner.invoke(main, ["paths", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["version"] == __version__
    assert payload["package"].endswith("manicure")
    assert payload["addon"].endswith("addon.py")
    assert Path(payload["storage"]) == tmp_storage


# --------------------------------------------------------------------------- #
# doctor                                                                      #
# --------------------------------------------------------------------------- #


def _mock_which(found: bool) -> Any:
    return (lambda name: "/usr/bin/mitmdump") if found else (lambda name: None)


def test_doctor_happy_path(
    tmp_storage: Path, monkeypatch: pytest.MonkeyPatch, free_port: int
) -> None:
    monkeypatch.setattr("manicure.cli.shutil.which", _mock_which(True))
    # Force the two default ports to appear free by patching _port_in_use.
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)
    result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 0
    assert "all checks passed" in result.stdout
    assert "ok    python" in result.stdout
    assert "ok    mitmdump" in result.stdout
    assert "ok    addon" in result.stdout
    assert "ok    storage" in result.stdout


def test_doctor_reports_missing_mitmdump(
    tmp_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("manicure.cli.shutil.which", _mock_which(False))
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)
    result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 1
    assert "fail  mitmdump" in result.output
    assert "uv tool install --force manicure" in result.output
    assert "check(s) failed" in result.output


def test_doctor_warns_when_ports_are_busy(
    tmp_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("manicure.cli.shutil.which", _mock_which(True))
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: True)
    result = runner.invoke(main, ["doctor"])
    # Port warnings are not fatal, so exit code is still 0.
    assert result.exit_code == 0
    assert "warn  proxy port" in result.stdout
    assert "warn  web port" in result.stdout


def test_doctor_fails_when_storage_unwritable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Point storage at a file (not a directory) — mkdir will succeed
    # creating parents but the write probe will fail with OSError.
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a dir")
    monkeypatch.setenv("MANICURE_STORAGE_DIR", str(blocker))
    monkeypatch.setattr("manicure.cli.shutil.which", _mock_which(True))
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)
    from manicure import config

    config.get_settings.cache_clear()
    result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 1
    assert "fail  storage" in result.output


# --------------------------------------------------------------------------- #
# start                                                                       #
# --------------------------------------------------------------------------- #


def test_start_print_command_does_not_exec(
    tmp_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--print-command` must short-circuit before os.execvpe."""
    monkeypatch.setattr("manicure.cli.shutil.which", lambda _: "/usr/bin/mitmdump")
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)
    exec_spy = MagicMock()
    monkeypatch.setattr("manicure.cli.os.execvpe", exec_spy)

    result = runner.invoke(main, ["start", "--print-command"])
    assert result.exit_code == 0
    # Should echo the full invocation string.
    assert "mitmdump" in result.stdout
    assert "reverse:https://api.anthropic.com" in result.stdout
    assert "--listen-port" in result.stdout
    exec_spy.assert_not_called()


def test_start_print_command_respects_port_and_upstream(
    tmp_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("manicure.cli.shutil.which", lambda _: "/usr/bin/mitmdump")
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)
    monkeypatch.setattr("manicure.cli.os.execvpe", MagicMock())

    result = runner.invoke(
        main,
        [
            "start",
            "--proxy-port",
            "9000",
            "--web-port",
            "9001",
            "--upstream",
            "https://example.test",
            "--print-command",
        ],
    )
    assert result.exit_code == 0
    assert "9000" in result.stdout
    assert "reverse:https://example.test" in result.stdout


def test_start_refuses_when_proxy_port_is_busy(
    tmp_storage: Path, busy_port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("manicure.cli.shutil.which", lambda _: "/usr/bin/mitmdump")
    # Force the port check to flag exactly the proxy port.
    monkeypatch.setattr(
        "manicure.cli._port_in_use",
        lambda p: p == busy_port,
    )
    exec_spy = MagicMock()
    monkeypatch.setattr("manicure.cli.os.execvpe", exec_spy)

    result = runner.invoke(
        main,
        [
            "start",
            "--proxy-port",
            str(busy_port),
            "--web-port",
            "8788",
            "--print-command",
        ],
    )
    assert result.exit_code == 2
    assert "already in use" in result.output
    exec_spy.assert_not_called()


def test_start_refuses_when_mitmdump_missing(
    tmp_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("manicure.cli.shutil.which", lambda _: None)
    exec_spy = MagicMock()
    monkeypatch.setattr("manicure.cli.os.execvpe", exec_spy)

    result = runner.invoke(main, ["start", "--print-command"])
    assert result.exit_code == 2
    assert "`mitmdump` was not found" in result.output
    assert "uv tool install --force manicure" in result.output
    exec_spy.assert_not_called()


def test_start_fails_when_addon_missing(
    tmp_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_traversable = MagicMock()
    fake_traversable.is_file.return_value = False

    def _fake_files(_pkg: str) -> Any:
        root = MagicMock()
        root.__truediv__.return_value = fake_traversable
        return root

    monkeypatch.setattr("manicure.cli.files", _fake_files)
    exec_spy = MagicMock()
    monkeypatch.setattr("manicure.cli.os.execvpe", exec_spy)

    result = runner.invoke(main, ["start", "--print-command"])
    assert result.exit_code == 2
    assert "could not locate the manicure mitmproxy addon" in result.output
    exec_spy.assert_not_called()


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #


def test_port_in_use_detects_busy_port(busy_port: int) -> None:
    assert _port_in_use(busy_port) is True


def test_port_in_use_reports_free_port(free_port: int) -> None:
    assert _port_in_use(free_port) is False


# --------------------------------------------------------------------------- #
# Help surfaces                                                               #
# --------------------------------------------------------------------------- #


def test_root_help_includes_quick_start_epilog() -> None:
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "manicure" in result.output
    assert "Quick start" in result.output or "quick start" in result.output.lower()


def test_start_help_includes_examples() -> None:
    result = runner.invoke(main, ["start", "--help"])
    assert result.exit_code == 0
    assert "Examples" in result.output or "example" in result.output.lower()
    assert "--proxy-port" in result.output
    assert "--print-command" in result.output


def test_doctor_help_renders() -> None:
    result = runner.invoke(main, ["doctor", "--help"])
    assert result.exit_code == 0
    assert "diagnose" in result.output.lower()


def test_paths_help_renders() -> None:
    result = runner.invoke(main, ["paths", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.output
