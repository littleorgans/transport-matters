"""Doctor coverage for managed CLI capability lines."""

from __future__ import annotations

from typing import TYPE_CHECKING

from typer.testing import CliRunner

from transport_matters.capabilities import CliCapability
from transport_matters.cli import main

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

runner = CliRunner()


def _stub_healthy_doctor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "transport_matters.cli.diagnose.resolve_mitmdump_executable",
        lambda **_kwargs: "/bin/mitmdump",
    )
    monkeypatch.setattr(
        "transport_matters.cli.diagnose.port_in_use",
        lambda _port: False,
    )
    monkeypatch.setattr(
        "transport_matters.cli.diagnose.resolve_database_url",
        lambda _settings: "postgresql://test/transport_matters",
    )
    monkeypatch.setattr(
        "transport_matters.cli.diagnose.current_revision",
        lambda _database_url: "head",
    )
    monkeypatch.setattr(
        "transport_matters.cli.diagnose.migration_head",
        lambda: "head",
    )


def test_doctor_reports_managed_cli_capabilities(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_healthy_doctor(monkeypatch)
    monkeypatch.setattr(
        "transport_matters.cli.diagnose.detect_clis",
        lambda: {
            "claude": CliCapability(
                installed=True,
                path="/bin/claude",
                version="claude 1.2.3",
            ),
            "codex": CliCapability(installed=False, path=None, version=None),
        },
    )

    result = runner.invoke(main, ["doctor"])

    assert result.exit_code == 0
    assert "ok    claude — claude 1.2.3" in result.output
    assert "warn  missing codex" in result.output
