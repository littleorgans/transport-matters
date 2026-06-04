"""Tests for ``transport_matters.cli.ports.allocate_port_pair``.

Three behaviours pinned per the Phase 2 spec:

- Returns two distinct free TCP ports.
- Retries on collision (kernel double-assignment — defensive).
- Raises :class:`PortAllocationError` after the attempt budget is
  exhausted, with the underlying ``OSError`` chained.
"""

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from transport_matters.cli.ports import (
    DEFAULT_ATTEMPTS,
    PortAllocationError,
    allocate_port_pair,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

# --------------------------------------------------------------------------- #
# Real socket: smoke-test the happy path with the kernel in the loop.        #
# --------------------------------------------------------------------------- #


def test_returns_two_distinct_free_ports() -> None:
    p1, p2 = allocate_port_pair()
    assert p1 != p2
    assert 1024 <= p1 <= 65535
    assert 1024 <= p2 <= 65535
    # Sockets are closed on return; the ports are advisory only and
    # may be picked up by anyone, so no liveness assertion here.


def test_each_call_returns_a_fresh_pair() -> None:
    """Two consecutive allocations should — almost certainly — differ.

    The kernel cycles ephemeral ports, so back-to-back allocations
    rarely collide. We accept the (vanishingly small) probability
    that one port matches by checking the *pair* differs, not the
    individual ports.
    """
    pair_a = allocate_port_pair()
    pair_b = allocate_port_pair()
    assert pair_a != pair_b


# --------------------------------------------------------------------------- #
# Mocked socket: pin retry + exhaustion semantics deterministically.          #
# --------------------------------------------------------------------------- #


class _FakeSocket:
    """Minimal socket stand-in for testing port allocation control flow.

    Records bind calls and reports a configurable port number from
    ``getsockname``. Supports the context-manager protocol so the
    production code's ``with socket.socket(...) as s`` pattern works.
    """

    def __init__(self, port: int) -> None:
        self.port = port
        self.closed = False

    def __enter__(self) -> _FakeSocket:
        return self

    def __exit__(self, *_: object) -> None:
        self.closed = True

    def bind(self, _addr: tuple[str, int]) -> None:
        pass

    def getsockname(self) -> tuple[str, int]:
        return ("127.0.0.1", self.port)

    def close(self) -> None:
        self.closed = True


@contextmanager
def _fake_sockets(
    monkeypatch: pytest.MonkeyPatch, port_sequence: list[int]
) -> Iterator[list[_FakeSocket]]:
    """Patch :func:`socket.socket` to yield ``_FakeSocket(port)`` for each
    item in *port_sequence*."""
    issued: list[_FakeSocket] = []
    iterator = iter(port_sequence)

    def _factory(*_args: Any, **_kwargs: Any) -> _FakeSocket:
        try:
            port = next(iterator)
        except StopIteration as exc:  # pragma: no cover — test-author bug
            raise AssertionError("ran out of fake ports") from exc
        sock = _FakeSocket(port)
        issued.append(sock)
        return sock

    monkeypatch.setattr("transport_matters.cli.ports.socket.socket", _factory)
    yield issued


def test_retries_on_kernel_double_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the kernel returns the same port for both sockets, retry."""
    # Attempt 1: both sockets get port 5000 → collision → retry.
    # Attempt 2: 6000 / 6001 → success.
    with _fake_sockets(monkeypatch, [5000, 5000, 6000, 6001]) as issued:
        result = allocate_port_pair(attempts=3)
    assert result == (6000, 6001)
    # All four sockets must be closed on the way out — no leaks.
    assert all(s.closed for s in issued)


def test_retries_on_bind_oserror_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient OSError on bind must trigger a retry, not propagate."""
    call_count = {"n": 0}

    def _factory(*_args: Any, **_kwargs: Any) -> Any:
        call_count["n"] += 1
        # First two socket() calls (one attempt's pair) raise on bind,
        # subsequent calls return real-ish fake sockets.
        if call_count["n"] <= 2:

            class _Boom:
                def __enter__(self) -> _Boom:
                    return self

                def __exit__(self, *_: object) -> None:
                    pass

                def bind(self, _addr: tuple[str, int]) -> None:
                    raise OSError(98, "address already in use")

                def getsockname(self) -> tuple[str, int]:  # pragma: no cover
                    return ("127.0.0.1", 0)

            return _Boom()
        port = 7000 if call_count["n"] == 3 else 7001
        return _FakeSocket(port)

    monkeypatch.setattr("transport_matters.cli.ports.socket.socket", _factory)
    assert allocate_port_pair(attempts=2) == (7000, 7001)


def test_raises_after_attempts_exhausted_on_oserror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Always-failing bind exhausts the retry budget, raising
    :class:`PortAllocationError` chained on the last OSError."""

    def _factory(*_args: Any, **_kwargs: Any) -> Any:
        sock = MagicMock()
        sock.__enter__ = MagicMock(return_value=sock)
        sock.__exit__ = MagicMock(return_value=None)
        sock.bind.side_effect = OSError(98, "address already in use")
        return sock

    monkeypatch.setattr("transport_matters.cli.ports.socket.socket", _factory)

    with pytest.raises(PortAllocationError) as info:
        allocate_port_pair(attempts=2)

    assert "2 attempts" in str(info.value)
    assert "--proxy-port" in str(info.value)
    assert isinstance(info.value.__cause__, OSError)


def test_raises_after_persistent_collisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If every attempt returns colliding ports, exhaust and raise."""
    with (
        _fake_sockets(monkeypatch, [9000, 9000, 9000, 9000]),
        pytest.raises(PortAllocationError) as info,
    ):
        allocate_port_pair(attempts=2)
    assert "2 attempts" in str(info.value)


def test_default_attempt_count() -> None:
    """The default attempt budget matches the module constant.

    Stops a future regression where someone tweaks the default at the
    function signature and forgets the docstring rationale.
    """
    assert DEFAULT_ATTEMPTS == 3
