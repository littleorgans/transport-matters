"""Orphan-run sweep helpers for ``transport-matters doctor``.

Pure functions + thin httpx client — fully unit-testable without a live
server.  ``run_doctor`` in :mod:`transport_matters.cli.diagnose` calls these
and formats the output; no I/O happens here beyond the HTTP requests.

JSON field names match the camelCase serialisation aliases from
:class:`~transport_matters.api.v1.run_routes.RunViewModel`
(``by_alias=True`` in ``_response_payload``).

Non-terminal :class:`~transport_matters.run_manager.RunState` values:
  ``starting``, ``running``
Terminal values:
  ``stopping``, ``exited``, ``failed``
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

_NON_TERMINAL_STATES: frozenset[str] = frozenset({"starting", "running"})


def runs_base_url(settings: Settings) -> str:
    """Return the loopback base URL for the local API server."""
    return loopback_http_url(settings.web_port)


def fetch_runs(base_url: str, *, timeout: float = 2.0) -> list[dict[str, object]] | None:
    """GET ``{base_url}/api/runs`` and return the ``runs`` list.

    Returns ``None`` on connection error (API not running).  Non-connection
    HTTP errors are raised so they surface to the caller.
    """
    try:
        response = httpx.get(f"{base_url}/api/runs", timeout=timeout)
        if not response.is_success:
            response.raise_for_status()
        data = response.json()
        return list(data["runs"])
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
    """Return runs that are candidates for orphan reaping.

    A candidate satisfies ALL of:
    - ``state`` is non-terminal (``starting`` or ``running``)
    - ``viewerCount == 0``
    - ``viewerlessSince`` is not ``None``
    - ``now - parse(viewerlessSince) >= older_than``

    NOTE: a minimized/docked run and a crash orphan are indistinguishable
    server-side (both meet the criteria above).  The operator decides.
    """
    candidates: list[dict[str, object]] = []
    for run in runs:
        state = run.get("state", "")
        if state not in _NON_TERMINAL_STATES:
            continue
        viewer_count = run.get("viewerCount", 1)
        if viewer_count != 0:
            continue
        viewerless_since_raw = run.get("viewerlessSince")
        if viewerless_since_raw is None:
            continue
        viewerless_since = datetime.fromisoformat(str(viewerless_since_raw))
        # Ensure timezone-aware comparison.
        if viewerless_since.tzinfo is None:
            viewerless_since = viewerless_since.replace(tzinfo=UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        age = now - viewerless_since
        if age < older_than:
            continue
        candidates.append(run)
    return candidates


def reap_run(base_url: str, run_id: str, *, timeout: float = 5.0) -> bool:
    """DELETE ``{base_url}/api/runs/{run_id}`` and return True on success."""
    try:
        response = httpx.delete(f"{base_url}/api/runs/{run_id}", timeout=timeout)
        return response.is_success
    except httpx.HTTPError:
        return False
