"""Durable per-run owned-launch facts (§11.1, slice 8b-ii): ``<run_dir>/sessions.json``.

Tier-1 must be a complete source of truth for the OWNED launch state, so a future §10.5 rebuild
re-resolves transcript paths faithfully WITHOUT the live launch env. The transcript bytes are owned
by the 8b-i snapshot; this module owns the launch FACTS a rebuild needs to bind them back: the
native session id, the ``source_descriptor`` (which now carries the managed ``home_dir``), the cli,
``minted``, and ``home_dir``.

The manifest carries ``home_dir`` too, but it is a liveness beacon unlinked on process exit
(``cli/launch_runtime.py``), so it cannot be the durable home. ``index.jsonl`` is the durable run
marker (``index/maintenance.py`` ``iter_run_dirs``); ``sessions.json`` sits beside it in the same run
dir, so the same enumeration finds both.

DAG: like the 8b-i transcript snapshot, the WRITE is a storage concern the ``index`` layer must not
import. Here it is even simpler than 8b-i's injected callback: the owned facts are LAUNCH-authoritative
(the launcher mints the id + descriptor + home_dir and KNOWS whether it minted — the launch profile),
so the cli launcher (the composition root that already imports storage) writes them directly, once, at
launch — before any wire frame and surviving process exit. ``minted`` is the launch-side twin of
``index.ingest.bind_exchange``'s read-side derivation (see ``LaunchProfile.mints_session_id``).

Single-writer per run dir: ``run_id`` is a fresh uuid per launch, so each run dir has one writer and
``sessions.json`` is written once. The upsert keyed on ``native_session_id`` keeps the write idempotent
and tolerates a run dir that hosts more than one owned session (the same per-session granularity the
transcript snapshot uses).
"""

import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from transport_matters.storage.disk_layout import DiskStorageLayout


class OwnedSessionFacts(BaseModel):
    """The owned-launch facts for one managed session (§11.1), durable for a §10.5 rebuild."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    cli: str  # claude | codex | ...
    native_session_id: str  # the id the launcher minted (claude --session-id / codex rollout uuid)
    minted: bool  # True = native id adopted as the session_id PK (claude); False = synth PK (codex)
    source_descriptor: str  # JSON ``TranscriptSource`` of the owned transcript, incl. ``home_dir``
    home_dir: str | None = (
        None  # managed ``--home-dir`` the transcript root resolves under; None = native
    )


class RunSessionFacts(BaseModel):
    """The ``<run_dir>/sessions.json`` document: every owned session for one run (§11.1)."""

    model_config = ConfigDict(frozen=True)

    sessions: list[OwnedSessionFacts]


def read_run_session_facts(storage_root: Path) -> RunSessionFacts | None:
    """Read the durable owned-launch facts for a run dir, or ``None`` when none were written.

    The §10.5-rebuild-side read of what :func:`write_owned_session_facts` persists; ``None`` for a run
    with no owned session (proxy-only / external adoption) or a dir predating slice 8b-ii."""
    path = DiskStorageLayout(storage_root).sessions_facts_path
    if not path.exists():
        return None
    return RunSessionFacts.model_validate_json(path.read_text(encoding="utf-8"))


def write_owned_session_facts(storage_root: Path, facts: OwnedSessionFacts) -> Path:
    """Upsert *facts* into ``<storage_root>/sessions.json`` (§11.1) and return the path.

    Idempotent and atomic: the entry is keyed on ``native_session_id`` (replacing any prior entry for
    the same owned session), and the document is rewritten via a ``.tmp`` + ``replace`` so a crashed
    write never leaves a half-written file a rebuild would choke on. The dir is created if absent (the
    run dir exists at launch via the per-run lock, but an explicit ``--storage-dir`` may not yet)."""
    layout = DiskStorageLayout(storage_root)
    path = layout.sessions_facts_path
    existing = read_run_session_facts(storage_root)
    others = (
        [s for s in existing.sessions if s.native_session_id != facts.native_session_id]
        if existing is not None
        else []
    )
    document = RunSessionFacts(sessions=[*others, facts])
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f"{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(document.model_dump_json(indent=2))
    tmp_path.replace(path)
    return path
