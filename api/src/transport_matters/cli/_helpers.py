"""Plain helpers for ``transport_matters.cli`` tests.

Lives outside ``conftest.py`` so the conftest stays focused on pytest
fixtures and hooks. Pytest does not collect this module because the
filename does not match ``test_*.py`` / ``*_test.py``.
"""

import re
from typing import TYPE_CHECKING, Any

from transport_matters.manifest import Manifest
from transport_matters.manifest import write as _manifest_write
from transport_matters.workspace import run_root, workspace_id

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


# Typer's `OptionHighlighter` (typer/rich_utils.py) registers two
# overlapping regex groups on flag strings:
#
#   (?P<switch>\-\w+)          # matches `-json` inside `--json`
#   (?P<option>\-\-[\w\-]+)    # matches the full `--json`
#
# On `--json`, both fire: the `option` span covers [0,6), the `switch`
# span covers [1,6). Rich's `Text.render` splits at every span boundary,
# producing two adjacent runs: `[0,1) = "-"` and `[1,6) = "-json"`,
# each styled bold, which serialises as
# `\x1b[1m-\x1b[0m\x1b[1m-json\x1b[0m` and breaks substring matches for
# the raw flag.
#
# `NO_COLOR=1` strips color (`Segment.remove_color`) but not style
# (bold/underline SGR codes still render), and on GitHub Actions Typer
# hard-forces `FORCE_TERMINAL=True` whenever `GITHUB_ACTIONS` is set, so
# neither env var alone silences the problem. Stripping SGR escapes
# before asserting is the simplest fix.
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """Strip ANSI SGR escapes so plain substring assertions work."""
    return _ANSI_ESCAPE.sub("", text)


def _which_all(path: str = "/usr/bin/mitmdump") -> Any:
    """``shutil.which`` stub that resolves any lookup to *path*."""
    resolved = path
    return lambda _name, path=None: resolved


def _which_none() -> Any:
    """``shutil.which`` stub that resolves every lookup to ``None``."""
    return lambda _name, path=None: None


def _which_by_name(mapping: dict[str, str | None]) -> Any:
    """``shutil.which`` stub that resolves per-name."""

    def _which(name: str, path: str | None = None) -> str | None:
        return mapping.get(name)

    return _which


def _patch_allocate_pairs(
    monkeypatch: pytest.MonkeyPatch, pairs: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Patch launch and retry port allocation with a deterministic sequence."""
    pool = iter(pairs)
    drawn: list[tuple[int, int]] = []

    def _alloc(*_a: Any, **_k: Any) -> tuple[int, int]:
        pair = next(pool)
        drawn.append(pair)
        return pair

    monkeypatch.setattr("transport_matters.cli.allocate_port_pair", _alloc)
    monkeypatch.setattr("transport_matters.cli.bind_retry.allocate_port_pair", _alloc)
    return drawn


def _sample_manifest(
    *,
    workdir: Path,
    storage: Path,
    pid: int,
    proxy_port: int = 8787,
    web_port: int = 8788,
    run_id: str = "run-001",
) -> Manifest:
    """Build a Manifest with sane defaults for the test under inspection."""
    wid = workspace_id(workdir)
    return Manifest(
        cwd=str(workdir),
        pid=pid,
        proxy_port=proxy_port,
        web_port=web_port,
        storage_dir=str(storage),
        run_id=run_id,
        started_at="2026-04-15T12:00:00+00:00",
        transport_matters_version="0.5.0",
        slug=wid.slug,
        hash=wid.hash,
    )


def _write_run_manifest(workdir: Path, m: Manifest) -> Path:
    """Materialise *m* at its per-run directory and return that directory.

    The directory is ``{slug}/{hash}/{run_id}/`` under *workdir*'s
    workspace, matching where a live launch would place lock + manifest.
    """
    run_dir = run_root(workdir, m.run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    _manifest_write(run_dir / "manifest.json", m)
    return run_dir
