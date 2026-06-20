"""Tests for ``transport-matters tail``."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
import typer
from typer.testing import CliRunner

from transport_matters import env_keys
from transport_matters.cli import main
from transport_matters.cli.desktop_runtime import desktop_log_path
from transport_matters.cli.tail_cmd import run_tail

from ._helpers import _plain

runner = CliRunner()

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from transport_matters.channel import ChannelSpec


def test_tail_help_lists_options() -> None:
    result = runner.invoke(main, ["tail", "--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "--follow" in output
    assert "--lines" in output
    assert "desktop.log" in output


def _patched_spec(
    channel_spec_factory: Callable[[str], ChannelSpec],
    patch_channel_specs: Callable[..., None],
    tmp_path: Path,
) -> ChannelSpec:
    spec = replace(channel_spec_factory("tm_tail"), home=tmp_path / "tm-home")
    patch_channel_specs(spec)
    return spec


def test_tail_prints_last_lines(
    channel_spec_factory: Callable[[str], ChannelSpec],
    patch_channel_specs: Callable[..., None],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(env_keys.HOME, raising=False)
    spec = _patched_spec(channel_spec_factory, patch_channel_specs, tmp_path)
    log_file = desktop_log_path(spec.home)
    log_file.parent.mkdir(parents=True)
    log_file.write_text("one\ntwo\nthree\n", encoding="utf-8")

    run_tail(channel="tmp", lines=2, follow=False)

    assert capsys.readouterr().out == "two\nthree\n"


def test_tail_follow_prints_appends_until_keyboard_interrupt(
    channel_spec_factory: Callable[[str], ChannelSpec],
    patch_channel_specs: Callable[..., None],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(env_keys.HOME, raising=False)
    spec = _patched_spec(channel_spec_factory, patch_channel_specs, tmp_path)
    log_file = desktop_log_path(spec.home)
    log_file.parent.mkdir(parents=True)
    log_file.write_text("one\ntwo\n", encoding="utf-8")
    sleep_calls = 0

    def fake_sleep(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 1:
            with log_file.open("a", encoding="utf-8") as handle:
                handle.write("three\n")
            return
        raise KeyboardInterrupt

    run_tail(channel="tmp", lines=1, follow=True, sleep=fake_sleep)

    assert capsys.readouterr().out == "two\nthree\n"


def test_tail_missing_log_exits_with_exact_path(
    channel_spec_factory: Callable[[str], ChannelSpec],
    patch_channel_specs: Callable[..., None],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(env_keys.HOME, raising=False)
    spec = _patched_spec(channel_spec_factory, patch_channel_specs, tmp_path)

    with pytest.raises(typer.Exit) as exc:
        run_tail(channel="tmp", lines=100, follow=False)

    assert exc.value.exit_code == 1
    assert str(desktop_log_path(spec.home)) in capsys.readouterr().err
