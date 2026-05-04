"""Tests for ``transport_matters.cli.prompt`` — system-prompt injection helpers."""

from __future__ import annotations

import pytest

from transport_matters.cli.prompt import (
    build_system_prompt,
    inject_system_prompt,
    user_supplied_system_prompt,
)

# --------------------------------------------------------------------------- #
# build_system_prompt                                                         #
# --------------------------------------------------------------------------- #


def test_build_system_prompt_includes_both_urls() -> None:
    msg = build_system_prompt(proxy_port=9000, web_port=9001)
    assert "running inside Transport Matters" in msg
    assert "http://127.0.0.1:9000" in msg
    assert "http://127.0.0.1:9001" in msg


def test_build_system_prompt_distinguishes_proxy_from_web() -> None:
    msg = build_system_prompt(proxy_port=9000, web_port=9001)
    # Order matters in the rendered string: the model needs to know
    # which URL is which.
    proxy_idx = msg.index("Proxy URL")
    web_idx = msg.index("Inspector UI")
    assert proxy_idx < web_idx


# --------------------------------------------------------------------------- #
# user_supplied_system_prompt                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "passthrough",
    [
        [],
        ["--model", "sonnet"],
        ["-p", "fix the bug"],
        ["--print-text"],  # near-collision: shares prefix but is unrelated
        ["--system-prompts"],  # close but not exact, should not match
        ["--system-prompt-file", "x.txt"],  # similar prefix without `=`
    ],
)
def test_user_supplied_system_prompt_false(passthrough: list[str]) -> None:
    assert user_supplied_system_prompt(passthrough) is False


@pytest.mark.parametrize(
    "passthrough",
    [
        ["--system-prompt", "you are X"],
        ["--append-system-prompt", "you are X"],
        ["--system-prompt=you are X"],
        ["--append-system-prompt=you are X"],
        ["--model", "sonnet", "--system-prompt", "you are X"],
        ["--system-prompt", "you are X", "--model", "sonnet"],
    ],
)
def test_user_supplied_system_prompt_true(passthrough: list[str]) -> None:
    assert user_supplied_system_prompt(passthrough) is True


# --------------------------------------------------------------------------- #
# inject_system_prompt                                                        #
# --------------------------------------------------------------------------- #


def test_inject_prepends_to_passthrough() -> None:
    out = inject_system_prompt(["--model", "sonnet"], proxy_port=8000, web_port=8001)
    assert out[0] == "--append-system-prompt"
    assert "http://127.0.0.1:8000" in out[1]
    assert "http://127.0.0.1:8001" in out[1]
    assert out[2:] == ["--model", "sonnet"]


def test_inject_into_empty_passthrough() -> None:
    out = inject_system_prompt([], proxy_port=8000, web_port=8001)
    assert len(out) == 2
    assert out[0] == "--append-system-prompt"


def test_inject_does_not_mutate_input() -> None:
    src = ["--model", "sonnet"]
    inject_system_prompt(src, proxy_port=8000, web_port=8001)
    assert src == ["--model", "sonnet"]
