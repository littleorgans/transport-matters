"""Run sweep helpers for ``transport-matters doctor``.

Pure functions + thin httpx client, fully unit-testable without a live
server.  ``run_doctor`` in :mod:`transport_matters.cli.diagnose` calls these
and formats the output; no I/O happens here beyond the HTTP requests.

JSON field names match the camelCase serialisation aliases from
:class:`~transport_matters.api.v1.run_routes.RunViewModel`
(``by_alias=True`` in ``_response_payload``).

Non-terminal :class:`~transport_matters.run_manager.RunState` values:
  ``RUNNING``
Terminal values:
  ``TERMINATING``, ``TERMINATED``, ``EXITED``, ``FAILED``
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx

from .net import loopback_http_url

if TYPE_CHECKING:
    from transport_matters.config import Settings

__all__ = [
    "fetch_runs",
    "orphan_candidates",
    "reap_run",
    "runs_base_url",
]

_NON_TERMINAL_STATES: frozenset[str] = frozenset({"RUNNING"})


def runs_base_url(settings: Settings) -> str:
    """Return the loopback base URL for the local API server."""
    return loopback_http_url(settings.web_port)


def fetch_runs(base_url: str, *, timeout: float = 2.0) -> list[dict[str, object]] | None:
    """GET ``{base_url}/v1/runs`` and return the ``items`` list.

    Returns ``None`` on connection error (API not running).  Non-connection
    HTTP errors are raised so they surface to the caller.
    """
    try:
        response = httpx.get(f"{base_url}/v1/runs", timeout=timeout)
        if not response.is_success:
            response.raise_for_status()
        data = response.json()
        return list(data["items"])
    except httpx.ConnectError:
        return None
    except httpx.TimeoutException:
        return None


def orphan_candidates(
    runs: list[dict[str, object]],
    *,
    older_than: timedelta,
    now: datetime,
) -> list[dict[str, object]]:
    """Return long-running runs that are candidates for operator review.

    A candidate satisfies ALL of:
    - ``state`` is non-terminal (``RUNNING``)
    - ``createdAt`` is present
    - ``now - parse(createdAt) >= older_than``

    The curated B6 run shape intentionally hides viewer internals. The operator
    decides whether a long-running captured run is stale enough to terminate.
    """
    candidates: list[dict[str, object]] = []
    for run in runs:
        state = run.get("state", "")
        if state not in _NON_TERMINAL_STATES:
            continue
        created_at_raw = run.get("createdAt")
        if created_at_raw is None:
            continue
        created_at = datetime.fromisoformat(str(created_at_raw))
        # Ensure timezone-aware comparison.
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        age = now - created_at
        if age < older_than:
            continue
        candidates.append(run)
    return candidates


def reap_run(base_url: str, run_id: str, *, timeout: float = 5.0) -> bool:
    """POST ``{base_url}/v1/runs/{run_id}/terminate`` and return True on success."""
    try:
        response = httpx.post(f"{base_url}/v1/runs/{run_id}/terminate", timeout=timeout)
        return response.is_success
    except httpx.HTTPError:
        return False
