"""Signal handler tests for `manicure.supervisor`."""

from __future__ import annotations

import signal

from manicure.supervisor import ProcessSupervisor

pytest_plugins = ("manicure.test_supervisor_support",)


def test_install_and_restore_signal_handlers() -> None:
    prev_sigint = signal.getsignal(signal.SIGINT)
    prev_sigterm = signal.getsignal(signal.SIGTERM)

    sup = ProcessSupervisor()
    sup.install_signal_handlers()
    try:
        assert signal.getsignal(signal.SIGINT) != prev_sigint
        assert signal.getsignal(signal.SIGTERM) != prev_sigterm
    finally:
        sup.restore_signal_handlers()

    assert signal.getsignal(signal.SIGINT) == prev_sigint
    assert signal.getsignal(signal.SIGTERM) == prev_sigterm


def test_install_signal_handlers_is_idempotent() -> None:
    sup = ProcessSupervisor()
    sup.install_signal_handlers()
    try:
        after_first = signal.getsignal(signal.SIGINT)
        sup.install_signal_handlers()
        assert signal.getsignal(signal.SIGINT) == after_first
    finally:
        sup.restore_signal_handlers()


def test_on_signal_records_first_only() -> None:
    sup = ProcessSupervisor()
    assert sup.received_signal is None
    sup._on_signal(signal.SIGINT, None)
    assert sup.received_signal == int(signal.SIGINT)
    sup._on_signal(signal.SIGTERM, None)
    assert sup.received_signal == int(signal.SIGINT)
