"""Doctor coverage for graceful CLI capability detection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from typer.testing import CliRunner

from transport_matters.capabilities import CliCapability
from transport_matters.cli import main
from transport_matters.cli.test_diagnose_capabilities import _stub_healthy_doctor

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

runner = CliRunner()


def test_doctor_reports_present_cli_with_unknown_version(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_healthy_doctor(monkeypatch)
    monkeypatch.setattr(
        "transport_matters.cli.diagnose.detect_clis",
        lambda: {
            "claude": CliCapability(installed=True, path="/bin/claude", version=None),
            "codex": CliCapability(installed=False, path=None, version=None),
        },
    )

    result = runner.invoke(main, ["doctor"])

    assert result.exit_code == 0
    assert "ok    claude — version unknown" in result.output
    assert "warn  missing claude" not in result.output
