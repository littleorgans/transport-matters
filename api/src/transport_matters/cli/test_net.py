"""Tests for the port-probing helpers in ``transport_matters.cli.net``."""

import pytest
import typer

from transport_matters.cli import port_in_use
from transport_matters.cli.net import validate_port_option


def test_port_in_use_detects_busy_port(busy_port: int) -> None:
    assert port_in_use(busy_port) is True


def test_port_in_use_reports_free_port(free_port: int) -> None:
    assert port_in_use(free_port) is False


def test_port_in_use_ignores_recently_closed_listener(
    recently_closed_port: int,
) -> None:
    assert port_in_use(recently_closed_port) is False


# --------------------------------------------------------------------------- #
# validate_port_option                                                        #
# --------------------------------------------------------------------------- #


def test_validate_port_passes_none_through() -> None:
    """``None`` means "the user omitted the flag" — let allocation decide."""
    assert validate_port_option(None) is None


@pytest.mark.parametrize("value", [1, 1024, 8787, 49152, 65535])
def test_validate_port_accepts_valid_range(value: int) -> None:
    assert validate_port_option(value) == value


@pytest.mark.parametrize("value", [0, -1, 65536, 99999])
def test_validate_port_rejects_out_of_range(value: int) -> None:
    """Reject 0 too: it would silently flow into ``--listen-port 0`` and
    into the injected system-prompt URL as ``http://127.0.0.1:0``."""
    with pytest.raises(typer.BadParameter) as exc_info:
        validate_port_option(value)
    msg = str(exc_info.value)
    assert "1..65535" in msg
    assert str(value) in msg
    # Hint must point users at the "omit the flag" escape hatch.
    assert "Omit the flag" in msg
