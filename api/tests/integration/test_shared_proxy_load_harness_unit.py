"""Fast checks for the opt-in shared proxy load harness."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from tests.integration import shared_proxy_load_harness as harness
from transport_matters.index.commit_dispatcher import commit_shard_index

if TYPE_CHECKING:
    from pathlib import Path


def _passing_metrics(*, cpu: float) -> harness.LoadMetrics:
    return harness.LoadMetrics(
        runs=50,
        requests_per_run=2,
        register_p95_ms=94.4,
        register_mean_ms=54.0,
        traffic=harness.TrafficMetrics(
            total_requests=100,
            failed_requests=0,
            contamination_count=0,
            p95_request_ms=809.1,
            mean_request_ms=774.5,
        ),
        capture=harness.CaptureMetrics(
            entries_total=100,
            missing_entries=0,
            wrong_run_entries=0,
        ),
        terminal_ws_echo_p95_ms=0.3,
        terminal_ws_echo_mean_ms=0.2,
        head_of_line=harness.HeadOfLineMetrics(
            healthy_completed=49,
            poison_errors=1,
            healthy_completed_before_poison=True,
            p95_healthy_ms=24.8,
            pool_usage_max=50,
            pool_usage_limit=50,
        ),
        proxy_cpu_peak_percent=cpu,
        verdict="pending",
    )


def test_cpu_peak_requires_real_samples() -> None:
    with pytest.raises(RuntimeError, match="CPU sampling failed, verdict indeterminate"):
        harness._proxy_cpu_peak_percent([])


def test_verdict_carries_fidelity_caveat() -> None:
    verdict = harness._verdict(_passing_metrics(cpu=143.8))

    assert verdict.startswith("saturates at ~50, bounded pool recommended")
    assert "directional, not a tight bound" in verdict
    assert "terminal echo bypasses proxy" in verdict
    assert "no keep-alive" in verdict


def test_head_of_line_probe_uses_dispatcher_shard_routing() -> None:
    session_ids = harness._unique_shard_session_ids(5, 7)

    assert len({commit_shard_index(session_id, 7) for session_id in session_ids}) == 5


async def test_drive_one_request_logs_failure(
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    run = harness.LoadRun(
        run_id="load-fail",
        harness="codex",
        listen_port=9,
        storage_root=tmp_path,
    )

    with caplog.at_level(logging.WARNING, logger=harness.__name__):
        _latency, failed, contaminated = await harness._drive_one_request(
            "http://127.0.0.1:9",
            run,
            0,
        )

    assert failed is True
    assert contaminated is False
    assert "load request failed for run_id=load-fail harness=codex seq=0" in caplog.text
