"""Plain helpers for ``manicure.cli`` tests.

Lives outside ``conftest.py`` so the conftest stays focused on pytest
fixtures and hooks. Pytest does not collect this module because the
filename does not match ``test_*.py`` / ``*_test.py``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from manicure.manifest import Manifest
from manicure.workspace import workspace_id

if TYPE_CHECKING:
    from pathlib import Path


# Typer's `OptionHighlighter` (typer/rich_utils.py) registers two
# overlapping regex groups on flag strings:
#
#   (?P<switch>\-\w+)          # matches `-json` inside `--json`
#   (?P<option>\-\-[\w\-]+)    # matches the full `--json`
#
# On `--json`, both fire: the `option` span covers [0,6), the `switch`
# span covers [1,6). Rich's `Text.render` splits at every span boundary,
# producing two adjacent runs — `[0,1) = "-"` and `[1,6) = "-json"`,
# each styled bold — which serialises as
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
    return lambda _name: path


def _which_none() -> Any:
    """``shutil.which`` stub that resolves every lookup to ``None``."""
    return lambda _name: None


def _which_by_name(mapping: dict[str, str | None]) -> Any:
    """``shutil.which`` stub that resolves per-name."""

    def _which(name: str) -> str | None:
        return mapping.get(name)

    return _which


def _sample_manifest(
    *,
    workdir: Path,
    storage: Path,
    pid: int,
    proxy_port: int = 8787,
    web_port: int = 8788,
) -> Manifest:
    """Build a Manifest with sane defaults for the test under inspection."""
    wid = workspace_id(workdir)
    return Manifest(
        cwd=str(workdir),
        pid=pid,
        proxy_port=proxy_port,
        web_port=web_port,
        storage_dir=str(storage),
        started_at="2026-04-15T12:00:00+00:00",
        manicure_version="0.5.0",
        slug=wid.slug,
        hash=wid.hash,
    )
