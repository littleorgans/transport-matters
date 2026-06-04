"""Tests for ``run_children`` — the supervisor-driven start lifecycle.

These tests drive ``run_children`` directly (no CLI) and assert how it
sequences ``ProcessSupervisor.spawn`` / ``wait_any`` / ``terminate_all``
under the four interesting outcomes: clean shutdown, signal during
``wait_for_port_ready``, signal after both children spawn, and proxy
exit after claude exits successfully.

Plus the bind-failure helpers (``failing_ports_from_log`` and
``handle_bind_failure``) used by the allocate-→-spawn retry loop —
isolated here so the regex/decision-table edge cases don't have to
go through the full CLI surface.
"""

import signal
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import typer

from transport_matters.cli import SIGNAL_EXIT, run_children
from transport_matters.cli.runner import (
    BindFailure,
    LaunchBindFailureOutcome,
    LaunchExitOutcome,
    LaunchRetryExhaustedOutcome,
    ManagedClient,
    failing_ports_from_log,
    format_retry_exhaustion,
    handle_bind_failure,
    run_client_children_until_outcome,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_run_children_spawns_claude_with_pty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The claude spawn must opt into the PTY path; the supervisor
    handles the TTY fallback internally."""
    fake_sup = MagicMock()
    fake_sup.received_signal = None
    fake_sup.wait_any.return_value = ("claude", 0)
    fake_sup.wait_one.return_value = ("mitmdump", 0)

    monkeypatch.setattr("transport_matters.cli.runner.ProcessSupervisor", lambda: fake_sup)
    monkeypatch.setattr("transport_matters.cli.runner.wait_for_port_ready", lambda *_a, **_k: True)

    with pytest.raises(typer.Exit):
        run_children(
            mitmdump_argv=["/bin/mitmdump"],
            mitmdump_env={},
            storage_dir=tmp_path,
            claude_argv=["/bin/claude"],
            claude_env={"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"},
            claude_cwd=tmp_path,
            proxy_port=8787,
            web_port=8788,
        )

    # Find the claude spawn call and assert the pty/foreground flags.
    claude_calls = [call for call in fake_sup.spawn.call_args_list if call.args[0] == "claude"]
    assert len(claude_calls) == 1
    kwargs = claude_calls[0].kwargs
    assert kwargs.get("pty") is True
    assert kwargs.get("foreground") is True


def test_run_children_bails_out_on_signal_before_claude_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If Ctrl+C arrives during the mitmdump readiness wait, we should
    terminate mitmdump and exit 0 *without* spawning claude — spawning
    just to tear down on the next line is wasteful.
    """
    fake_sup = MagicMock()
    # Signal flag is set from the start, as if SIGINT landed during
    # `wait_for_port_ready`. spawn("mitmdump") runs normally; the
    # branch fires before spawn("claude") gets a chance.
    fake_sup.received_signal = int(signal.SIGINT)

    monkeypatch.setattr("transport_matters.cli.runner.ProcessSupervisor", lambda: fake_sup)
    monkeypatch.setattr("transport_matters.cli.runner.wait_for_port_ready", lambda *_a, **_k: True)

    with pytest.raises(typer.Exit) as exc_info:
        run_children(
            mitmdump_argv=["/bin/mitmdump"],
            mitmdump_env={},
            storage_dir=tmp_path,
            claude_argv=["/bin/claude"],
            claude_env={"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"},
            claude_cwd=tmp_path,
            proxy_port=8787,
            web_port=8788,
        )
    assert exc_info.value.exit_code == 0

    # mitmdump was spawned; claude was NOT.
    spawn_names = [call.args[0] for call in fake_sup.spawn.call_args_list]
    assert spawn_names == ["mitmdump"]
    fake_sup.terminate_all.assert_called_once()
    # And we never reached wait_any — it would have been called after
    # the claude spawn we correctly skipped.
    fake_sup.wait_any.assert_not_called()


def test_run_children_exits_zero_on_signal_after_children_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_sup = MagicMock()
    fake_sup.received_signal = None
    fake_sup.wait_any.return_value = (SIGNAL_EXIT, int(signal.SIGINT))

    monkeypatch.setattr("transport_matters.cli.runner.ProcessSupervisor", lambda: fake_sup)
    monkeypatch.setattr("transport_matters.cli.runner.wait_for_port_ready", lambda *_a, **_k: True)

    with pytest.raises(typer.Exit) as exc_info:
        run_children(
            mitmdump_argv=["/bin/mitmdump"],
            mitmdump_env={},
            storage_dir=tmp_path,
            claude_argv=["/bin/claude"],
            claude_env={"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"},
            claude_cwd=tmp_path,
            proxy_port=8787,
            web_port=8788,
        )

    assert exc_info.value.exit_code == 0
    fake_sup.terminate_all.assert_called_once()


def test_run_children_reports_proxy_failure_after_claude_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_sup = MagicMock()
    fake_sup.received_signal = None
    fake_sup.wait_any.return_value = ("claude", 0)
    fake_sup.wait_one.return_value = ("mitmdump", 7)

    monkeypatch.setattr("transport_matters.cli.runner.ProcessSupervisor", lambda: fake_sup)
    monkeypatch.setattr("transport_matters.cli.runner.wait_for_port_ready", lambda *_a, **_k: True)

    with pytest.raises(typer.Exit) as exc_info:
        run_children(
            mitmdump_argv=["/bin/mitmdump"],
            mitmdump_env={},
            storage_dir=tmp_path,
            claude_argv=["/bin/claude"],
            claude_env={"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"},
            claude_cwd=tmp_path,
            proxy_port=8787,
            web_port=8788,
        )

    assert exc_info.value.exit_code == 1
    fake_sup.terminate_all.assert_called_once()


def test_run_client_children_handles_custom_client_exit_then_proxy_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_sup = MagicMock()
    fake_sup.received_signal = None
    fake_sup.wait_any.return_value = ("sample-client", 0)
    fake_sup.wait_one.return_value = ("mitmdump", 0)

    monkeypatch.setattr("transport_matters.cli.runner.ProcessSupervisor", lambda: fake_sup)
    monkeypatch.setattr("transport_matters.cli.runner.wait_for_port_ready", lambda *_a, **_k: True)

    outcome = run_client_children_until_outcome(
        mitmdump_argv=["/bin/mitmdump"],
        mitmdump_env={"TRANSPORT_MATTERS_RUN_ID": "run-001"},
        storage_dir=tmp_path,
        client=ManagedClient(
            name="sample-client",
            display_name="Sample Client",
            argv=["/bin/sample-client"],
            env={"SAMPLE": "1"},
            cwd=tmp_path,
        ),
        proxy_port=8787,
        web_port=8788,
    )

    assert outcome == LaunchExitOutcome(0)
    assert (
        "Sample Client exited; web UI still live at http://127.0.0.1:8788. Ctrl+C to stop."
    ) in capsys.readouterr().out
    mitmdump_call = fake_sup.spawn.call_args_list[0]
    assert mitmdump_call.args == ("mitmdump", ["/bin/mitmdump"])
    assert mitmdump_call.kwargs["env"] == {
        "TRANSPORT_MATTERS_RUN_ID": "run-001",
        "PYTHONUNBUFFERED": "1",
    }
    assert mitmdump_call.kwargs["log_path"] == tmp_path / "logs" / "mitmdump.log"
    client_call = fake_sup.spawn.call_args_list[1]
    assert client_call.args == ("sample-client", ["/bin/sample-client"])
    assert client_call.kwargs["env"] == {"SAMPLE": "1"}
    assert client_call.kwargs["cwd"] == tmp_path
    assert client_call.kwargs["foreground"] is True
    assert client_call.kwargs["pty"] is True
    fake_sup.wait_one.assert_called_once_with("mitmdump")
    fake_sup.terminate_all.assert_called_once()


def test_run_client_children_proxy_only_runs_mitmdump_in_foreground(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_sup = MagicMock()
    fake_sup.wait_one.return_value = ("mitmdump", 4)

    monkeypatch.setattr("transport_matters.cli.runner.ProcessSupervisor", lambda: fake_sup)

    outcome = run_client_children_until_outcome(
        mitmdump_argv=["/bin/mitmdump"],
        mitmdump_env={"TRANSPORT_MATTERS_RUN_ID": "run-001"},
        storage_dir=tmp_path,
        client=None,
        proxy_port=8787,
        web_port=8788,
    )

    assert outcome == LaunchExitOutcome(4)
    fake_sup.spawn.assert_called_once_with(
        "mitmdump",
        ["/bin/mitmdump"],
        env={"TRANSPORT_MATTERS_RUN_ID": "run-001"},
        foreground=True,
    )
    fake_sup.wait_one.assert_called_once_with("mitmdump")
    fake_sup.wait_any.assert_not_called()
    fake_sup.terminate_all.assert_not_called()


def test_run_client_children_outcome_captures_proxy_failure_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_sup = MagicMock()
    fake_sup.received_signal = None
    fake_sup.wait_any.return_value = ("claude", 0)
    fake_sup.wait_one.return_value = ("mitmdump", 7)

    monkeypatch.setattr("transport_matters.cli.runner.ProcessSupervisor", lambda: fake_sup)
    monkeypatch.setattr("transport_matters.cli.runner.wait_for_port_ready", lambda *_a, **_k: True)

    outcome = run_client_children_until_outcome(
        mitmdump_argv=["/bin/mitmdump"],
        mitmdump_env={},
        storage_dir=tmp_path,
        client=ManagedClient(
            name="claude",
            display_name="Claude",
            argv=["/bin/claude"],
            env={"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"},
            cwd=tmp_path,
        ),
        proxy_port=8787,
        web_port=8788,
    )

    assert outcome == LaunchExitOutcome(
        exit_code=1,
        error="mitmdump exited unexpectedly (rc=7).",
        log_path=tmp_path / "logs" / "mitmdump.log",
    )
    fake_sup.terminate_all.assert_called_once()


def test_run_client_children_outcome_captures_bind_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_sup = MagicMock()
    fake_sup.received_signal = None
    log = tmp_path / "logs" / "mitmdump.log"

    def _not_ready(*_args: object, **_kwargs: object) -> bool:
        log.write_text("EADDRINUSE ('127.0.0.1', 8787)\n")
        return False

    monkeypatch.setattr("transport_matters.cli.runner.ProcessSupervisor", lambda: fake_sup)
    monkeypatch.setattr("transport_matters.cli.runner.wait_for_port_ready", _not_ready)

    outcome = run_client_children_until_outcome(
        mitmdump_argv=["/bin/mitmdump"],
        mitmdump_env={},
        storage_dir=tmp_path,
        client=ManagedClient(
            name="claude",
            display_name="Claude",
            argv=["/bin/claude"],
            env={"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"},
            cwd=tmp_path,
        ),
        proxy_port=8787,
        web_port=8788,
    )

    assert isinstance(outcome, LaunchBindFailureOutcome)
    assert outcome.failure.proxy_port == 8787
    assert outcome.failure.web_port == 8788
    assert outcome.failure.failing_ports == (8787,)
    assert outcome.failure.log_path == log
    fake_sup.terminate_all.assert_called_once()


# --------------------------------------------------------------------------- #
# failing_ports_from_log                                                     #
# --------------------------------------------------------------------------- #


def test_failing_ports_from_log_returns_none_when_log_missing(
    tmp_path: Path,
) -> None:
    """No log on disk → caller can't tell bind-vs-other; returns None."""
    assert failing_ports_from_log(tmp_path / "absent.log", (8787,)) is None


def test_failing_ports_from_log_returns_none_when_no_bind_needles(
    tmp_path: Path,
) -> None:
    """Log exists but doesn't mention EADDRINUSE → not a bind failure;
    return None so the caller surfaces the original (non-retryable)
    error instead of looping pointlessly."""
    log = tmp_path / "mitm.log"
    log.write_text("Some unrelated mitmproxy startup error\nbad addon import\n")
    assert failing_ports_from_log(log, (8787, 8788)) is None


def test_failing_ports_from_log_extracts_darwin_errno(tmp_path: Path) -> None:
    """Darwin's mitmdump message: 'errno 48' + 'Address already in use'.
    The port should be picked out of the same line, filtered to ones we
    actually attempted (errno 48 is a number too — we ignore it)."""
    log = tmp_path / "mitm.log"
    log.write_text(
        "Error starting proxy server: error while attempting to bind on "
        "address ('127.0.0.1', 8787): [Errno 48] Address already in use\n"
    )
    assert failing_ports_from_log(log, (8787, 8788)) == (8787,)


def test_failing_ports_from_log_extracts_linux_errno(tmp_path: Path) -> None:
    """Linux uses errno 98, same message text. The errno also gets
    matched by the port regex but is filtered out because it's not in
    the attempted set."""
    log = tmp_path / "mitm.log"
    log.write_text("[Errno 98] Address already in use: ('127.0.0.1', 9000)\n")
    assert failing_ports_from_log(log, (9000,)) == (9000,)


def test_failing_ports_from_log_returns_empty_when_port_unattributable(
    tmp_path: Path,
) -> None:
    """EADDRINUSE present but no attempted port appears on the line.
    Returns empty tuple — caller treats that as 'bind failed but we
    can't pin which port', falling back to re-allocating both unpinned
    slots."""
    log = tmp_path / "mitm.log"
    log.write_text("EADDRINUSE during reverse-proxy startup\n")
    assert failing_ports_from_log(log, (8787, 8788)) == ()


def test_failing_ports_from_log_falls_back_to_errno_when_phrases_missing(
    tmp_path: Path,
) -> None:
    """Defensive fallback: a future mitmproxy that drops the
    human-readable EADDRINUSE phrases (both 'Address already in use'
    and 'EADDRINUSE') would silently break the log scanner. Python's
    OSError repr keeps emitting `[Errno 48]` on Darwin and
    `[Errno 98]` on Linux regardless of what mitmproxy decides to
    print around it, so we match on those too. Pin both Darwin and
    Linux variants in one test — there's only one production
    `_BIND_NEEDLES` tuple to break."""
    log = tmp_path / "mitm.log"
    log.write_text(
        "bind ('127.0.0.1', 8787) failed: [Errno 48]\nbind ('127.0.0.1', 8788) failed: [Errno 98]\n"
    )
    # Both lines should match independently and contribute their port.
    assert failing_ports_from_log(log, (8787, 8788)) == (8787, 8788)


# --------------------------------------------------------------------------- #
# handle_bind_failure                                                        #
# --------------------------------------------------------------------------- #


def _make_failure(
    *,
    proxy_port: int,
    web_port: int,
    failing_ports: tuple[int, ...],
    tmp_path: Path,
) -> BindFailure:
    return BindFailure(
        proxy_port=proxy_port,
        web_port=web_port,
        failing_ports=failing_ports,
        log_path=tmp_path / "mitm.log",
    )


def test_handle_bind_failure_pinned_web_port_fails_fast(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Web slot user-pinned and named in failing_ports → typer.Exit(2),
    do not call the allocator."""
    spy = MagicMock()
    monkeypatch.setattr("transport_matters.cli.runner.allocate_port_pair", spy)

    exc = _make_failure(proxy_port=12000, web_port=8788, failing_ports=(8788,), tmp_path=tmp_path)
    with pytest.raises(typer.Exit) as exc_info:
        handle_bind_failure(
            exc,
            proxy_port=12000,
            web_port=8788,
            proxy_user_supplied=False,
            web_user_supplied=True,
        )
    assert exc_info.value.exit_code == 2
    spy.assert_not_called()


def test_handle_bind_failure_both_pinned_anonymous_failure_fails_fast(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Log signalled EADDRINUSE but couldn't extract a port; both slots
    are pinned, so there's nothing left to safely re-allocate. Exit 2."""
    spy = MagicMock()
    monkeypatch.setattr("transport_matters.cli.runner.allocate_port_pair", spy)

    exc = _make_failure(proxy_port=9000, web_port=9001, failing_ports=(), tmp_path=tmp_path)
    with pytest.raises(typer.Exit) as exc_info:
        handle_bind_failure(
            exc,
            proxy_port=9000,
            web_port=9001,
            proxy_user_supplied=True,
            web_user_supplied=True,
        )
    assert exc_info.value.exit_code == 2
    spy.assert_not_called()


def test_handle_bind_failure_reallocates_only_named_unpinned_slot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Failing names the proxy port; web is fine (and unpinned). Only
    the proxy slot should swap; web stays put."""
    monkeypatch.setattr(
        "transport_matters.cli.runner.allocate_port_pair",
        lambda: (60001, 60002),
    )
    exc = _make_failure(proxy_port=12000, web_port=12001, failing_ports=(12000,), tmp_path=tmp_path)
    new_proxy, new_web = handle_bind_failure(
        exc,
        proxy_port=12000,
        web_port=12001,
        proxy_user_supplied=False,
        web_user_supplied=False,
    )
    assert new_proxy == 60001
    # Web wasn't named in failing_ports, so we keep it.
    assert new_web == 12001


def test_handle_bind_failure_anonymous_failure_replaces_all_unpinned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Log couldn't pin the port; both slots unpinned → swap both."""
    monkeypatch.setattr(
        "transport_matters.cli.runner.allocate_port_pair",
        lambda: (50000, 50001),
    )
    exc = _make_failure(proxy_port=12000, web_port=12001, failing_ports=(), tmp_path=tmp_path)
    new_proxy, new_web = handle_bind_failure(
        exc,
        proxy_port=12000,
        web_port=12001,
        proxy_user_supplied=False,
        web_user_supplied=False,
    )
    assert (new_proxy, new_web) == (50000, 50001)


def test_handle_bind_failure_keeps_pinned_proxy_when_only_web_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Proxy is user-pinned but failing names the (unpinned) web port —
    swap web only, leave the user's proxy choice alone."""
    monkeypatch.setattr(
        "transport_matters.cli.runner.allocate_port_pair",
        lambda: (60001, 60002),
    )
    exc = _make_failure(proxy_port=9000, web_port=12001, failing_ports=(12001,), tmp_path=tmp_path)
    new_proxy, new_web = handle_bind_failure(
        exc,
        proxy_port=9000,
        web_port=12001,
        proxy_user_supplied=True,
        web_user_supplied=False,
    )
    assert new_proxy == 9000
    assert new_web == 60002


def test_handle_bind_failure_propagates_allocator_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If the kernel can't hand out a fresh pair during retry, exit 2
    with the allocator's message rather than a confusing retry-loop one."""
    from transport_matters.cli.ports import PortAllocationError

    def _raise() -> tuple[int, int]:
        raise PortAllocationError("kernel said no")

    monkeypatch.setattr("transport_matters.cli.runner.allocate_port_pair", _raise)

    exc = _make_failure(proxy_port=12000, web_port=12001, failing_ports=(), tmp_path=tmp_path)
    with pytest.raises(typer.Exit) as exc_info:
        handle_bind_failure(
            exc,
            proxy_port=12000,
            web_port=12001,
            proxy_user_supplied=False,
            web_user_supplied=False,
        )
    assert exc_info.value.exit_code == 2


def test_format_retry_exhaustion_highlights_pinned_ports() -> None:
    outcome = LaunchRetryExhaustedOutcome(
        attempted=((54321, 9001), (60001, 9001), (60003, 9001)),
        proxy_port=60003,
        web_port=9001,
        proxy_user_supplied=False,
        web_user_supplied=True,
    )

    message = "\n".join(format_retry_exhaustion(outcome))

    assert "could not bind ports after 3 attempts" in message
    assert "Tried (proxy, web): (54321, 9001), (60001, 9001), (60003, 9001)." in message
    assert "Pinned (held constant across all attempts): --web-port 9001." in message
    assert "Free the pinned port" in message
    assert "Pin specific values" not in message
