"""Tests for :mod:`transport_matters.cli.runs_health`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx

from transport_matters.cli.runs_health import fetch_runs, orphan_candidates, reap_run

if TYPE_CHECKING:
    import pytest

_NOW = datetime(2026, 6, 14, 12, 0, 0, tzinfo=UTC)
_OLDER_THAN = timedelta(seconds=300)
_CREATED_OLD = "2026-06-14T11:50:00+00:00"
_CREATED_YOUNG = "2026-06-14T11:58:00+00:00"


def _run(
    *,
    run_id: str = "run-abc",
    harness: str = "claude",
    workspace_id: str = "workspace/hash",
    session_id: str = "session-abc",
    state: str = "RUNNING",
    created_at: str | None = _CREATED_OLD,
) -> dict[str, object]:
    r: dict[str, object] = {
        "runId": run_id,
        "workspaceId": workspace_id,
        "sessionId": session_id,
        "harness": harness,
        "state": state,
    }
    if created_at is not None:
        r["createdAt"] = created_at
    return r


def test_orphan_candidates_includes_running_old_run() -> None:
    runs = [_run(state="RUNNING", created_at=_CREATED_OLD)]
    result = orphan_candidates(runs, older_than=_OLDER_THAN, now=_NOW)
    assert len(result) == 1
    assert result[0]["runId"] == "run-abc"


def test_orphan_candidates_excludes_terminal_states() -> None:
    runs = [
        _run(run_id="terminating", state="TERMINATING"),
        _run(run_id="terminated", state="TERMINATED"),
        _run(run_id="exited", state="EXITED"),
        _run(run_id="failed", state="FAILED"),
    ]
    assert orphan_candidates(runs, older_than=_OLDER_THAN, now=_NOW) == []


def test_orphan_candidates_excludes_missing_created_at() -> None:
    runs = [_run(state="RUNNING", created_at=None)]
    assert orphan_candidates(runs, older_than=_OLDER_THAN, now=_NOW) == []


def test_orphan_candidates_excludes_too_young() -> None:
    runs = [_run(state="RUNNING", created_at=_CREATED_YOUNG)]
    assert orphan_candidates(runs, older_than=_OLDER_THAN, now=_NOW) == []


def test_orphan_candidates_exactly_at_threshold() -> None:
    created_at = (_NOW - _OLDER_THAN).isoformat()
    runs = [_run(state="RUNNING", created_at=created_at)]
    assert len(orphan_candidates(runs, older_than=_OLDER_THAN, now=_NOW)) == 1


def test_orphan_candidates_mixed_list() -> None:
    runs = [
        _run(run_id="keep", state="RUNNING", created_at=_CREATED_OLD),
        _run(run_id="skip-young", state="RUNNING", created_at=_CREATED_YOUNG),
        _run(run_id="skip-ended", state="EXITED", created_at=_CREATED_OLD),
        _run(run_id="skip-missing-created", state="RUNNING", created_at=None),
    ]
    result = orphan_candidates(runs, older_than=_OLDER_THAN, now=_NOW)
    assert [r["runId"] for r in result] == ["keep"]


def test_fetch_runs_returns_items_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    runs_payload = [_run(run_id="r1"), _run(run_id="r2")]

    def _ok(*_a: object, **_k: object) -> httpx.Response:
        return httpx.Response(200, json={"items": runs_payload, "nextCursor": None})

    monkeypatch.setattr(httpx, "get", _ok)
    result = fetch_runs("http://127.0.0.1:8788")
    assert result is not None
    assert len(result) == 2
    assert result[0]["runId"] == "r1"


def test_fetch_runs_calls_v1_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _ok(url: str, **_k: object) -> httpx.Response:
        calls.append(url)
        return httpx.Response(200, json={"items": [], "nextCursor": None})

    monkeypatch.setattr(httpx, "get", _ok)
    assert fetch_runs("http://127.0.0.1:8788") == []
    assert calls == ["http://127.0.0.1:8788/v1/runs"]


def test_fetch_runs_connect_error_via_monkeypatch(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: object, **_k: object) -> httpx.Response:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", _raise)
    assert fetch_runs("http://127.0.0.1:8788") is None


def test_fetch_runs_timeout_via_monkeypatch(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: object, **_k: object) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(httpx, "get", _raise)
    assert fetch_runs("http://127.0.0.1:8788") is None


def test_reap_run_posts_terminate_and_returns_true_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _ok(url: str, **_k: object) -> httpx.Response:
        calls.append(url)
        return httpx.Response(200, json={"run": {"runId": "run-abc", "state": "TERMINATED"}})

    monkeypatch.setattr(httpx, "post", _ok)
    assert reap_run("http://127.0.0.1:8788", "run-abc") is True
    assert calls == ["http://127.0.0.1:8788/v1/runs/run-abc/terminate"]


def test_reap_run_returns_false_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    def _not_found(*_a: object, **_k: object) -> httpx.Response:
        return httpx.Response(404, json={"code": "not_found"})

    monkeypatch.setattr(httpx, "post", _not_found)
    assert reap_run("http://127.0.0.1:8788", "run-missing") is False


def test_reap_run_returns_false_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: object, **_k: object) -> httpx.Response:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", _raise)
    assert reap_run("http://127.0.0.1:8788", "run-abc") is False
