"""Phase 2 acceptance tests for ``manicure start``.

Exercises the product-level features that landed alongside the
``cli/`` decomposition: kernel-allocated port pairs, automatic
``--append-system-prompt`` injection, and the bounded retry loop the
spec mandates for the allocate-→-spawn TOCTOU race. Kept separate
from ``test_start.py`` so the bulk start surface stays under the
per-file LOC budget.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from transport_matters.cli import BindFailure, main

from ._helpers import _patch_allocate_pairs, _which_all, _which_by_name

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


# --------------------------------------------------------------------------- #
# start: dynamic port allocation                                              #
# --------------------------------------------------------------------------- #


def test_start_dynamic_ports_appear_in_print_command(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """Without explicit port flags, ``allocate_port_pair`` hands us a
    kernel-assigned proxy + web pair, and both surface in the printed
    invocations: the proxy via mitmdump's ``--listen-port`` and the web
    port via the injected system-prompt URL on the claude argv line."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)
    monkeypatch.setattr(
        "transport_matters.cli.allocate_port_pair", lambda *_a, **_k: (54321, 54322)
    )

    result = runner.invoke(main, ["claude", "--print-command"])
    assert result.exit_code == 0, result.output
    # Proxy port lands on the mitmdump line as --listen-port.
    assert "54321" in result.stdout
    # Web port surfaces via the injected system-prompt URL on the claude
    # line — that's the contract of the print-command output now.
    assert "http://127.0.0.1:54322" in result.stdout


def test_start_explicit_proxy_port_overrides_allocation(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """Explicit ``--proxy-port`` wins over the allocator's proxy slot;
    the web slot still comes from the allocator and shows up via the
    injected system-prompt URL on the claude line."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    sentinel = MagicMock(return_value=(11111, 22222))
    monkeypatch.setattr("transport_matters.cli.allocate_port_pair", sentinel)

    result = runner.invoke(
        main,
        ["claude", "--proxy-port", "9000", "--print-command"],
    )
    assert result.exit_code == 0, result.output
    # The user's port is honoured for the proxy listener.
    assert "--listen-port 9000" in result.stdout
    # Allocator still ran (web port is missing) but the allocated proxy
    # value is discarded; only the allocated web port lands in output.
    assert "11111" not in result.stdout
    assert "http://127.0.0.1:22222" in result.stdout


def test_start_port_allocation_error_surfaces_actionable_message(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """When the kernel can't hand us a free pair, exit 2 with a message
    telling the user how to recover (pin --proxy-port / --web-port)."""
    from transport_matters.cli import PortAllocationError

    def _raise(*_a: Any, **_k: Any) -> tuple[int, int]:
        raise PortAllocationError("kernel said no")

    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli.allocate_port_pair", _raise)

    result = runner.invoke(main, ["claude", "--no-claude", "--print-command"])
    assert result.exit_code == 2
    assert "kernel said no" in result.output
    spy_run_children.assert_not_called()


@pytest.mark.parametrize("bad_port", ["0", "-1", "65536", "99999"])
def test_start_rejects_out_of_range_port_values(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
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
    spy_run_children.assert_not_called()


# --------------------------------------------------------------------------- #
# start: system-prompt injection                                              #
# --------------------------------------------------------------------------- #


def test_start_injects_system_prompt_by_default(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """Default behaviour: prepend ``--append-system-prompt`` with the
    proxy + inspector URLs so the model knows it is inside transport_matters."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    result = runner.invoke(
        main, ["claude", "--proxy-port", "9000", "--web-port", "9001"]
    )
    assert result.exit_code == 0, result.output
    argv = spy_run_children.call_args.kwargs["claude_argv"]
    # `claude_argv` = [claude_path, *passthrough]; injection prepends
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
    spy_run_children: MagicMock,
) -> None:
    """``--no-system-prompt`` short-circuits the auto-injection branch."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    result = runner.invoke(main, ["claude", "--no-system-prompt"])
    assert result.exit_code == 0, result.output
    argv = spy_run_children.call_args.kwargs["claude_argv"]
    assert "--append-system-prompt" not in argv
    assert argv == ["/bin/claude"]


def test_start_user_supplied_system_prompt_wins(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """If the user passes their own ``--system-prompt`` (or
    ``--append-system-prompt``) after ``--``, manicure must NOT also
    inject — the user's prompt wins."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    result = runner.invoke(main, ["claude", "--", "--system-prompt", "you are X"])
    assert result.exit_code == 0, result.output
    argv = spy_run_children.call_args.kwargs["claude_argv"]
    # Exactly one --system-prompt (the user's) and zero
    # --append-system-prompt (manicure stayed out of it).
    assert argv.count("--system-prompt") == 1
    assert "--append-system-prompt" not in argv
    # User's prompt token survives intact.
    assert "you are X" in argv


def test_start_user_supplied_append_system_prompt_wins(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """Same as above for ``--append-system-prompt`` — manicure detects
    either flag and stays out of the way."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    result = runner.invoke(
        main,
        ["claude", "--proxy-port", "9000", "--", "--append-system-prompt", "extra"],
    )
    assert result.exit_code == 0, result.output
    argv = spy_run_children.call_args.kwargs["claude_argv"]
    # Only the user's --append-system-prompt is present (manicure's
    # injection would have added a second).
    assert argv.count("--append-system-prompt") == 1
    # And manicure's URL is NOT in the prompt — only the user's "extra".
    assert "extra" in argv
    assert not any("http://localhost:9000" in tok for tok in argv)
    assert not any("http://127.0.0.1:9000" in tok for tok in argv)


# --------------------------------------------------------------------------- #
# start: bounded allocate-→-spawn retry loop                                   #
# --------------------------------------------------------------------------- #


def test_start_retries_after_bind_failure_then_succeeds(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
    tmp_path: Path,
) -> None:
    """First spawn raises ``BindFailure`` (port stolen between allocate and
    spawn); the retry loop draws a fresh pair via ``allocate_port_pair``
    and the second spawn succeeds. Exit 0, allocator called twice (initial
    + one re-allocation), second ``_run_children`` invocation receives the
    re-allocated ports."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)
    drawn = _patch_allocate_pairs(monkeypatch, [(54321, 54322), (60001, 60002)])

    log_path = tmp_path / "mitmdump.log"

    def _side_effect(**kwargs: Any) -> None:
        # Raise on the first invocation, succeed on the second.
        if spy_run_children.call_count == 1:
            raise BindFailure(
                proxy_port=kwargs["proxy_port"],
                web_port=kwargs["web_port"],
                # Empty failing_ports = "log said EADDRINUSE but couldn't
                # pin which port", which forces a re-allocation of every
                # unpinned slot — the conservative retry path.
                failing_ports=(),
                log_path=log_path,
            )

    spy_run_children.side_effect = _side_effect

    result = runner.invoke(main, ["claude"])
    assert result.exit_code == 0, result.output
    # Both pairs drawn: initial allocation + retry-time re-allocation.
    assert drawn == [(54321, 54322), (60001, 60002)]
    # _run_children called twice; second call uses re-allocated ports.
    assert spy_run_children.call_count == 2
    second_kwargs = spy_run_children.call_args_list[1].kwargs
    assert second_kwargs["proxy_port"] == 60001
    assert second_kwargs["web_port"] == 60002


def test_start_exhausts_retry_budget_with_actionable_message(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
    tmp_path: Path,
) -> None:
    """All 3 spawn attempts raise ``BindFailure``: exit 1 with a message
    naming the attempted port pairs and pointing the user at
    ``--proxy-port`` / ``--web-port`` flags."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)
    drawn = _patch_allocate_pairs(
        monkeypatch,
        [(54321, 54322), (60001, 60002), (60003, 60004)],
    )

    log_path = tmp_path / "mitmdump.log"

    def _side_effect(**kwargs: Any) -> None:
        raise BindFailure(
            proxy_port=kwargs["proxy_port"],
            web_port=kwargs["web_port"],
            failing_ports=(),
            log_path=log_path,
        )

    spy_run_children.side_effect = _side_effect

    result = runner.invoke(main, ["claude"])
    assert result.exit_code == 1
    # Three attempts exactly; no fourth allocator call (the loop bails
    # before re-allocating on the final iteration).
    assert spy_run_children.call_count == 3
    assert drawn == [(54321, 54322), (60001, 60002), (60003, 60004)]
    # Exhaustion message names the attempted pairs and the recovery flags.
    assert "could not bind ports after 3 attempts" in result.output
    for proxy, web in drawn:
        assert f"({proxy}, {web})" in result.output
    assert "--proxy-port" in result.output
    assert "--web-port" in result.output


def test_start_exhaustion_message_highlights_pinned_flag(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
    tmp_path: Path,
) -> None:
    """One side pinned + repeated anonymous bind failures → the
    unpinned slot keeps getting re-allocated until the budget is
    exhausted. The exhaustion message must call out the pinned flag
    that stayed constant across all attempts, otherwise the user
    reads three pairs sharing the same pinned value and gets told
    to "pin specific values" — which they already did."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)
    # User pins web=9001. The proxy slot still draws from the allocator
    # initially, then the retry path re-allocates a fresh proxy each
    # time (web stays pinned because the user chose it).
    drawn = _patch_allocate_pairs(
        monkeypatch,
        [(54321, 11111), (60001, 22222), (60003, 33333)],
    )

    log_path = tmp_path / "mitmdump.log"

    def _side_effect(**kwargs: Any) -> None:
        # Anonymous failure (failing_ports=()) lets the retry path
        # re-allocate the unpinned proxy slot each time without
        # exiting fast on a pinned-port conflict.
        raise BindFailure(
            proxy_port=kwargs["proxy_port"],
            web_port=kwargs["web_port"],
            failing_ports=(),
            log_path=log_path,
        )

    spy_run_children.side_effect = _side_effect

    result = runner.invoke(main, ["claude", "--web-port", "9001"])
    assert result.exit_code == 1
    assert spy_run_children.call_count == 3
    # Allocator drew once initially (web=9001 ignored from that pair)
    # plus twice for retries; retry-time allocations only contribute
    # the proxy half because web stays pinned.
    assert drawn == [(54321, 11111), (60001, 22222), (60003, 33333)]
    # Exhaustion banner is unchanged.
    assert "could not bind ports after 3 attempts" in result.output
    # Pinned-flag callout: must name the flag and the value the user
    # supplied (held constant across every attempt).
    assert "Pinned (held constant across all attempts):" in result.output
    assert "--web-port 9001" in result.output
    # Recovery hint adapts: don't tell the user to "pin specific
    # values" when they already pinned. Suggest freeing the port or
    # omitting the flag instead.
    assert "Free the pinned port" in result.output
    assert "Pin specific values" not in result.output
    # Each attempt's pair still appears in the "Tried (proxy, web)" list
    # so the user can see which side rotated.
    for proxy, _web in drawn:
        assert f"({proxy}, 9001)" in result.output


def test_start_does_not_retry_when_pinned_port_is_in_use(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
    tmp_path: Path,
) -> None:
    """When the bind-failure log names a user-pinned port, fail fast with
    the spec's actionable message — never silently re-allocate the slot
    the user explicitly chose. ``_run_children`` runs exactly once."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)
    # Web port is unpinned, so the initial allocation still draws a pair
    # (the proxy half is discarded because the user pinned 9000).
    drawn = _patch_allocate_pairs(monkeypatch, [(50000, 60000)])

    log_path = tmp_path / "mitmdump.log"

    def _side_effect(**kwargs: Any) -> None:
        # Log named the pinned proxy port — the user's flag is the
        # broken one, retrying with a fresh proxy would silently mask
        # the bug they asked us to surface.
        raise BindFailure(
            proxy_port=kwargs["proxy_port"],
            web_port=kwargs["web_port"],
            failing_ports=(9000,),
            log_path=log_path,
        )

    spy_run_children.side_effect = _side_effect

    result = runner.invoke(main, ["claude", "--proxy-port", "9000"])
    assert result.exit_code == 2
    # Exactly one spawn attempt: no retry on a pinned-port conflict.
    assert spy_run_children.call_count == 1
    # Initial allocation only — `_handle_bind_failure` short-circuits
    # before re-allocating when the failure is pinned.
    assert drawn == [(50000, 60000)]
    # Message names the offending flag + value and points at recovery.
    assert "--proxy-port 9000" in result.output
    assert "Free the port" in result.output
