"""Tests for :mod:`transport_matters.cli.runs_health`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx

from transport_matters.cli.runs_health import fetch_runs, orphan_candidates, reap_run

if TYPE_CHECKING:
    import pytest

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 14, 12, 0, 0, tzinfo=UTC)
_OLDER_THAN = timedelta(seconds=300)

# Viewerless since 10 minutes ago — well past the threshold.
_VIEWERLESS_SINCE_OLD = "2026-06-14T11:50:00+00:00"
# Viewerless since 2 minutes ago — younger than 300s threshold.
_VIEWERLESS_SINCE_YOUNG = "2026-06-14T11:58:00+00:00"


def _run(
    *,
    run_id: str = "run-abc",
    cli: str = "claude",
    cwd: str = "/home/user/project",
    state: str = "running",
    viewer_count: int = 0,
    viewerless_since: str | None = _VIEWERLESS_SINCE_OLD,
    proxy_port: int = 9000,
) -> dict[str, object]:
    r: dict[str, object] = {
        "runId": run_id,
        "cli": cli,
        "cwd": cwd,
        "state": state,
        "viewerCount": viewer_count,
        "proxyPort": proxy_port,
    }
    if viewerless_since is not None:
        r["viewerlessSince"] = viewerless_since
    return r


# ---------------------------------------------------------------------------
# orphan_candidates — load-bearing filter tests
# ---------------------------------------------------------------------------


def test_orphan_candidates_includes_running_viewerless_old() -> None:
    """A RUNNING, viewerless, old-enough run is a candidate."""
    runs = [_run(state="running", viewer_count=0, viewerless_since=_VIEWERLESS_SINCE_OLD)]
    result = orphan_candidates(runs, older_than=_OLDER_THAN, now=_NOW)
    assert len(result) == 1
    assert result[0]["runId"] == "run-abc"


def test_orphan_candidates_includes_starting_viewerless_old() -> None:
    """A STARTING, viewerless, old-enough run is also a candidate."""
    runs = [_run(state="starting", viewer_count=0, viewerless_since=_VIEWERLESS_SINCE_OLD)]
    result = orphan_candidates(runs, older_than=_OLDER_THAN, now=_NOW)
    assert len(result) == 1


def test_orphan_candidates_excludes_active_viewer() -> None:
    """A run with viewer_count > 0 is excluded (active viewer present)."""
    runs = [_run(state="running", viewer_count=1, viewerless_since=_VIEWERLESS_SINCE_OLD)]
    result = orphan_candidates(runs, older_than=_OLDER_THAN, now=_NOW)
    assert result == []


def test_orphan_candidates_excludes_terminal_state_exited() -> None:
    """An exited run is excluded regardless of other fields."""
    runs = [_run(state="exited", viewer_count=0, viewerless_since=_VIEWERLESS_SINCE_OLD)]
    result = orphan_candidates(runs, older_than=_OLDER_THAN, now=_NOW)
    assert result == []


def test_orphan_candidates_excludes_terminal_state_failed() -> None:
    """A failed run is excluded."""
    runs = [_run(state="failed", viewer_count=0, viewerless_since=_VIEWERLESS_SINCE_OLD)]
    result = orphan_candidates(runs, older_than=_OLDER_THAN, now=_NOW)
    assert result == []


def test_orphan_candidates_excludes_terminal_state_stopping() -> None:
    """A stopping run is excluded."""
    runs = [_run(state="stopping", viewer_count=0, viewerless_since=_VIEWERLESS_SINCE_OLD)]
    result = orphan_candidates(runs, older_than=_OLDER_THAN, now=_NOW)
    assert result == []


def test_orphan_candidates_excludes_viewerless_since_none() -> None:
    """A run with no viewerless_since timestamp is excluded (never went viewerless)."""
    runs = [_run(state="running", viewer_count=0, viewerless_since=None)]
    result = orphan_candidates(runs, older_than=_OLDER_THAN, now=_NOW)
    assert result == []


def test_orphan_candidates_excludes_too_young() -> None:
    """A viewerless run younger than the threshold is excluded (restore transient guard)."""
    runs = [_run(state="running", viewer_count=0, viewerless_since=_VIEWERLESS_SINCE_YOUNG)]
    result = orphan_candidates(runs, older_than=_OLDER_THAN, now=_NOW)
    assert result == []


def test_orphan_candidates_exactly_at_threshold() -> None:
    """A run exactly at the threshold (age == older_than) is included."""
    viewerless_since = (_NOW - _OLDER_THAN).isoformat()
    runs = [_run(state="running", viewer_count=0, viewerless_since=viewerless_since)]
    result = orphan_candidates(runs, older_than=_OLDER_THAN, now=_NOW)
    assert len(result) == 1


def test_orphan_candidates_mixed_list() -> None:
    """Only the qualifying run is returned from a mixed list."""
    runs = [
        _run(
            run_id="keep", state="running", viewer_count=0, viewerless_since=_VIEWERLESS_SINCE_OLD
        ),
        _run(
            run_id="skip-viewer",
            state="running",
            viewer_count=2,
            viewerless_since=_VIEWERLESS_SINCE_OLD,
        ),
        _run(
            run_id="skip-young",
            state="running",
            viewer_count=0,
            viewerless_since=_VIEWERLESS_SINCE_YOUNG,
        ),
        _run(
            run_id="skip-exited",
            state="exited",
            viewer_count=0,
            viewerless_since=_VIEWERLESS_SINCE_OLD,
        ),
        _run(run_id="skip-no-vs", state="running", viewer_count=0, viewerless_since=None),
    ]
    result = orphan_candidates(runs, older_than=_OLDER_THAN, now=_NOW)
    assert [r["runId"] for r in result] == ["keep"]


# ---------------------------------------------------------------------------
# fetch_runs — mocked httpx
# ---------------------------------------------------------------------------


def test_fetch_runs_returns_list_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns the runs list from a 200 response."""
    runs_payload = [_run(run_id="r1"), _run(run_id="r2")]

    def _ok(*_a: object, **_k: object) -> httpx.Response:
        return httpx.Response(200, json={"runs": runs_payload})

    monkeypatch.setattr(httpx, "get", _ok)
    result = fetch_runs("http://127.0.0.1:8788")
    assert result is not None
    assert len(result) == 2
    assert result[0]["runId"] == "r1"


def test_fetch_runs_connect_error_via_monkeypatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns None on ConnectError (API not running)."""

    def _raise(*_a: object, **_k: object) -> httpx.Response:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", _raise)
    result = fetch_runs("http://127.0.0.1:8788")
    assert result is None


def test_fetch_runs_timeout_via_monkeypatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns None on TimeoutException."""

    def _raise(*_a: object, **_k: object) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(httpx, "get", _raise)
    result = fetch_runs("http://127.0.0.1:8788")
    assert result is None


def test_fetch_runs_200_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns runs list from a successful response."""
    runs_payload = [_run(run_id="r42")]

    def _ok(*_a: object, **_k: object) -> httpx.Response:
        return httpx.Response(200, json={"runs": runs_payload})

    monkeypatch.setattr(httpx, "get", _ok)
    result = fetch_runs("http://127.0.0.1:8788")
    assert result is not None
    assert result[0]["runId"] == "r42"


# ---------------------------------------------------------------------------
# reap_run — mocked httpx
# ---------------------------------------------------------------------------


def test_reap_run_returns_true_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns True when DELETE succeeds."""

    def _ok(*_a: object, **_k: object) -> httpx.Response:
        return httpx.Response(200, json={"runId": "run-abc", "state": "stopping"})

    monkeypatch.setattr(httpx, "delete", _ok)
    assert reap_run("http://127.0.0.1:8788", "run-abc") is True


def test_reap_run_returns_false_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns False when the run is not found."""

    def _not_found(*_a: object, **_k: object) -> httpx.Response:
        return httpx.Response(404, json={"code": "not_found"})

    monkeypatch.setattr(httpx, "delete", _not_found)
    assert reap_run("http://127.0.0.1:8788", "run-missing") is False


def test_reap_run_returns_false_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns False on any HTTPError."""

    def _raise(*_a: object, **_k: object) -> httpx.Response:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "delete", _raise)
    assert reap_run("http://127.0.0.1:8788", "run-abc") is False
