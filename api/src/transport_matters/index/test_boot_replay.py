"""Slice 8c-ii boot auto-replay: a stale schema gate REBUILDS tier-2 from tier-1 before the live
system starts, instead of the in-writer gate dropping it to empty (§10.5 / §13.2).

Real temp SQLite + seeded run dirs (never mocks; §13). Tier-1 seeding is shared with the 8c-i replay
suite via :mod:`transport_matters.index.test_replay_support`.
"""

import importlib
import threading
import time
from typing import TYPE_CHECKING

from transport_matters.index.db import connect
from transport_matters.index.rebuild import rebuild, rebuild_if_stale
from transport_matters.index.schema import apply_schema, is_rebuild_needed
from transport_matters.index.test_replay_support import _counts, _seed_claude_run

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _seed_stale_tier2(db_path: Path) -> None:
    """A current tier-2 db carrying a sentinel block, then a poisoned gated key (a derivation bump).

    The sentinel proves the boot path DROPS rather than merges: after the rebuild it must be gone,
    replaced by the tier-1 replay, never coexisting with it.
    """
    conn = connect(db_path)
    try:
        apply_schema(conn)
        conn.execute(
            "INSERT INTO block (hash, kind, text, identity_canonical) "
            "VALUES ('stale-sentinel', 'text', 'gone after rebuild', '{}')"
        )
        conn.execute("UPDATE schema_meta SET value = '0' WHERE key = 'adapters_version'")
    finally:
        conn.close()


class TestBootAutoReplay:
    """§10.5 / §13.2: ``rebuild_if_stale`` — boot replays tier-1 instead of dropping to empty."""

    def test_stale_gate_boot_rebuilds_from_tier1_not_empty(self, tmp_path: Path) -> None:
        sid = "00000000-0000-4000-8000-000000000011"
        _seed_claude_run(tmp_path, "run1", sid)

        # The 8c-i killer-demo counts as the reference: an explicit rebuild → full tier-1 counts.
        ref_db = tmp_path / "ref.db"
        rebuild(tmp_path, db_path=ref_db)
        ref = connect(ref_db)
        try:
            expected = _counts(ref)
        finally:
            ref.close()
        assert expected["wire_exchange"] >= 1
        assert expected["transcript_turn"] >= 1  # non-empty: there is real tier-1 to lose

        db = tmp_path / "index.db"
        _seed_stale_tier2(db)
        assert is_rebuild_needed(db) is True

        did = rebuild_if_stale(tmp_path, db_path=db, lock_path=tmp_path / "index.rebuild.lock")

        assert did is True
        got = connect(db)
        try:
            assert _counts(got) == expected  # rebuilt to full tier-1 counts, NOT dropped to empty
            sentinel = got.execute(
                "SELECT COUNT(*) FROM block WHERE hash = 'stale-sentinel'"
            ).fetchone()[0]
            assert sentinel == 0  # the stale db was DROPPED then replayed, not merged
        finally:
            got.close()
        assert is_rebuild_needed(db) is False  # gate now current → the in-writer gate won't drop

    def test_current_gate_boot_is_a_noop(self, tmp_path: Path) -> None:
        sid = "00000000-0000-4000-8000-000000000022"
        _seed_claude_run(tmp_path, "run1", sid)
        db = tmp_path / "index.db"
        rebuild(tmp_path, db_path=db)  # already current + populated
        before = connect(db)
        try:
            counts_before = _counts(before)
        finally:
            before.close()

        did = rebuild_if_stale(tmp_path, db_path=db, lock_path=tmp_path / "index.rebuild.lock")

        assert did is False  # current gate → no destructive pass
        after = connect(db)
        try:
            assert _counts(after) == counts_before  # untouched
        finally:
            after.close()

    def test_missing_db_boot_rebuilds_from_tier1(self, tmp_path: Path) -> None:
        sid = "00000000-0000-4000-8000-000000000033"
        _seed_claude_run(tmp_path, "run1", sid)
        db = tmp_path / "index.db"
        assert not db.exists()

        did = rebuild_if_stale(tmp_path, db_path=db, lock_path=tmp_path / "index.rebuild.lock")

        assert did is True
        got = connect(db)
        try:
            assert _counts(got)["wire_exchange"] >= 1  # populated from tier-1, from nothing
        finally:
            got.close()

    def test_single_flight_serializes_and_runs_exactly_one_rebuild(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Two concurrent boots that both see the stale gate must serialize on the lock; the loser
        # checks UNDER the lock, sees a now-current db, and skips — so rebuild() runs exactly once and
        # never corrupts the db (no second drop racing the first). Deterministic: boot A is held
        # mid-rebuild (lock held) while boot B blocks on the lock; only after A finishes does B check.
        sid = "00000000-0000-4000-8000-000000000044"
        _seed_claude_run(tmp_path, "run1", sid)
        db = tmp_path / "index.db"
        _seed_stale_tier2(db)
        lock_path = tmp_path / "index.rebuild.lock"

        # rebuild_if_stale calls the module global ``rebuild``; patch it on the rebuild MODULE (the
        # package __init__ re-exports the function under the same dotted path, so fetch the module via
        # importlib) so the gate counts real drops. ``rebuild`` imported at top is the original.
        rebuild_mod = importlib.import_module("transport_matters.index.rebuild")
        real_rebuild = rebuild
        calls: list[int] = []
        a_in_rebuild = threading.Event()
        a_may_proceed = threading.Event()

        def gated_rebuild(workspaces_root: Path, *, db_path: Path | None = None) -> None:
            a_in_rebuild.set()  # A holds the lock; the db is still intact (no drop yet)
            assert a_may_proceed.wait(timeout=5)
            calls.append(1)
            real_rebuild(workspaces_root, db_path=db_path)

        monkeypatch.setattr(rebuild_mod, "rebuild", gated_rebuild)

        result: dict[str, bool] = {}
        errors: list[BaseException] = []

        def boot_a() -> None:
            try:
                rebuild_if_stale(tmp_path, db_path=db, lock_path=lock_path)
            except BaseException as exc:  # surface a thread failure to the assert below
                errors.append(exc)

        def boot_b() -> None:
            try:
                result["b"] = rebuild_if_stale(tmp_path, db_path=db, lock_path=lock_path)
            except BaseException as exc:  # surface a thread failure to the assert below
                errors.append(exc)

        ta = threading.Thread(target=boot_a)
        ta.start()
        assert a_in_rebuild.wait(timeout=5)  # A is under the lock, inside the gated rebuild
        tb = threading.Thread(target=boot_b)
        tb.start()
        time.sleep(0.1)  # let B reach the lock and block on it while A still holds it
        a_may_proceed.set()  # A now drops + replays for real, then releases the lock
        ta.join(timeout=20)
        tb.join(timeout=20)

        assert not errors, errors
        assert len(calls) == 1  # exactly one destructive rebuild despite two concurrent boots
        assert result["b"] is False  # the waiting boot saw a current db and skipped its own pass
        got = connect(db)
        try:
            assert _counts(got)["wire_exchange"] >= 1  # rebuilt + uncorrupted
            assert (
                got.execute("SELECT COUNT(*) FROM block WHERE hash = 'stale-sentinel'").fetchone()[
                    0
                ]
                == 0
            )
        finally:
            got.close()
        assert is_rebuild_needed(db) is False
