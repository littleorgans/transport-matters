"""The `transport-matters paths` resolution logic.

Split out from ``cli/__init__.py`` so the package entry point stays
under the 700-LOC invariant and this module can own the workspace
selector semantics (``--workspace slug-or-cwd``) in one place.

Resolution order for the ``storage`` value:

1. If the caller passes a selector, treat it as a path (when it
   contains a path separator or expands via ``~``) or a slug. Paths
   canonicalise via :func:`workspace_id`; slugs go through a manifest
   scan under ``~/.transport-matters/workspaces/{slug}/``.
2. Otherwise prefer ``TRANSPORT_MATTERS_STORAGE_DIR`` from the
   environment. A session launched by ``transport-matters claude``
   carries its own run's storage dir there, so ``paths`` from inside a
   session is exact and unambiguous even when several runs share the CWD.
3. Failing that, prefer ``TRANSPORT_MATTERS_CWD`` (then ``Path.cwd()``)
   and scan that workspace container for live runs. Exactly one live run
   returns its ``storage_dir``. Zero live runs leaves storage unresolved:
   the static entries still print and the storage-derived ones render as
   null (exit 0), so a fresh install can locate the package. More than one
   is not a fault but an ambiguity a bare external shell cannot resolve, so
   ``paths`` lists the runs and asks you to pick one (exit 2). None of these
   branches create directories; ``paths`` is read-only.
"""

import json
import os
from importlib.resources import files
from pathlib import Path

import typer

from transport_matters import __version__, env_keys
from transport_matters.lock import WorkspaceLock
from transport_matters.manifest import Manifest, read, read_all
from transport_matters.storage_roots import default_workspaces_root
from transport_matters.workspace import workspace_root

from .identity import CLI_COMMAND

__all__ = ["resolve_paths"]


def resolve_paths(*, workspace: str | None, as_json: bool) -> None:
    """Body of ``transport-matters paths``.

    Resolves the storage root per ``workspace`` (see module docstring),
    then renders the standard set of path entries as either JSON or an
    aligned two-column table.
    """
    package_root = Path(str(files("transport_matters")))
    addon_path = package_root / "addon.py"
    www_path = package_root / "www"
    storage = _resolve_storage(workspace)

    # The static entries are always knowable from the install; the
    # storage-derived ones need a resolved session. With no session
    # ``storage`` is None and those entries render as null (JSON) or
    # "unresolved" (table) instead of aborting, so a fresh install can
    # still locate the package, addon, and bundled www.
    entries: dict[str, str | None] = {
        "version": __version__,
        "package": str(package_root),
        "addon": str(addon_path),
        "www": str(www_path),
        "storage": str(storage) if storage is not None else None,
        "exchanges": str(storage / "exchanges") if storage is not None else None,
        "rules": str(storage / "rules.json") if storage is not None else None,
        "index": str(storage / "index.jsonl") if storage is not None else None,
    }

    if as_json:
        typer.echo(json.dumps(entries, indent=2))
        return

    width = max(len(k) for k in entries)
    for key, value in entries.items():
        typer.echo(f"  {key.ljust(width)}  {value if value is not None else 'unresolved'}")
    if storage is None:
        typer.echo(
            f"\nNo live session; storage paths are unresolved. Run "
            f"`{CLI_COMMAND} list` or pass --workspace <slug-or-storage-dir>.",
            err=True,
        )


def _resolve_storage(selector: str | None) -> Path | None:
    """Return the storage path the entries should use, or None.

    None means there is no live session to resolve on a bare lookup (no
    selector, no env); ``paths`` then prints the static entries with
    storage unresolved. See the module docstring for the full order.
    """
    if selector is None:
        # A launched session carries its own run's storage dir in the env,
        # which is exact and survives the same-CWD multi-run case. Empty
        # string is treated as unset.
        env_storage = os.environ.get(env_keys.STORAGE_DIR) or None
        if env_storage:
            return Path(env_storage)
        # TRANSPORT_MATTERS_CWD wins over Path.cwd() so a paths lookup from a
        # Claude session spawned by ``transport-matters claude`` resolves to the
        # launching workspace even if the user has since ``cd``'d into
        # a subdirectory.
        env_cwd = os.environ.get(env_keys.CWD) or None
        return _storage_for_cwd(Path(env_cwd) if env_cwd else Path.cwd(), strict=False)

    # A path-shaped selector goes through CWD resolution; a bare token
    # is a slug. ``os.sep`` handles both POSIX and Windows uniformly,
    # and ``~`` catches the common home-relative case on any platform.
    if os.sep in selector or selector.startswith("~"):
        candidate = Path(selector).expanduser()
        # A path that names a known run's storage dir resolves to that run
        # directly — exactly the value the same-CWD ambiguity error prints,
        # so it must round-trip. Match recorded manifests (not a tree-prefix
        # or manifest-in-dir check) so it also covers --storage-dir runs whose
        # data lives outside the workspaces tree.
        if _names_known_storage(candidate):
            return candidate
        return _storage_for_cwd(candidate, strict=True)

    return _storage_for_slug(selector)


def _names_known_storage(candidate: Path) -> bool:
    """True if *candidate* is the ``storage_dir`` of any recorded run.

    Scans every manifest (live or stale, across all workspaces) and compares
    resolved paths, so a storage dir supplied to ``--workspace`` is recognised
    regardless of whether it lives inside the workspaces tree.
    """
    target = candidate.resolve(strict=False)
    return any(
        Path(m.storage_dir).resolve(strict=False) == target
        for m in read_all(default_workspaces_root())
    )


def _storage_for_cwd(cwd: Path, *, strict: bool) -> Path | None:
    """Return the storage path for *cwd*, or None when no live run is found.

    Scans the workspace container for live runs. Exactly one live run
    returns its ``storage_dir`` (which may be a ``--storage-dir`` override).
    More than one is ambiguous from a bare shell, so list them and exit.
    Zero live runs: an explicit ``--workspace <path>`` lookup (*strict*)
    errors, because the caller asked for that path specifically; the bare
    lookup returns None so ``paths`` still prints the static entries with
    storage unresolved. A launched session never reaches this because its
    own storage dir is in ``TRANSPORT_MATTERS_STORAGE_DIR``.
    """
    ws_root = workspace_root(cwd)
    live = _live_runs(ws_root)
    if len(live) > 1:
        _exit_ambiguous_runs(live)
    if not live:
        if not strict:
            return None
        typer.secho(
            f"error: no live Transport Matters instance for {cwd}.",
            fg=typer.colors.RED,
            err=True,
        )
        typer.echo(
            f"Start a session, run {CLI_COMMAND} list to see live instances, "
            "or pass --workspace <slug-or-storage-dir> to inspect a recorded run.",
            err=True,
        )
        raise typer.Exit(2)
    return Path(live[0].storage_dir)


def _storage_for_slug(slug: str) -> Path:
    """Resolve a slug to a storage path via manifest scan.

    A slug is a display aid; the on-disk identity is
    ``{slug}/{hash}/{run_id}/``, so multiple workspaces can share a slug
    when two distinct CWDs collapse to the same tail, and one workspace
    can hold several runs. We accept any manifest under
    ``{slug}/*/*/manifest.json`` (live or stale, so users can inspect a
    recently-exited instance's paths) but fail loudly on ambiguity.
    """
    root = default_workspaces_root() / slug
    candidates: list[Manifest] = []
    if root.is_dir():
        for manifest_path in sorted(root.glob("*/*/manifest.json")):
            m = read(manifest_path)
            if m is not None:
                candidates.append(m)

    if not candidates:
        typer.secho(
            f"error: no workspace matching {slug!r}.",
            fg=typer.colors.RED,
            err=True,
        )
        typer.echo(
            f"Run `{CLI_COMMAND} list` to see live workspaces, or pass a directory path.",
            err=True,
        )
        raise typer.Exit(2)
    if len(candidates) > 1:
        typer.secho(
            f"slug {slug!r} matches {len(candidates)} runs — pick one:",
            fg=typer.colors.YELLOW,
            err=True,
        )
        _print_run_choices(candidates)
        typer.echo(
            "Disambiguate by passing a storage path to --workspace instead.",
            err=True,
        )
        raise typer.Exit(2)
    return Path(candidates[0].storage_dir)


def _live_runs(ws_root: Path) -> list[Manifest]:
    """Return manifests of live runs under the workspace container *ws_root*.

    Read-only: probes each run's lock but never reaps. ``paths`` leaves
    stale-manifest cleanup to ``transport-matters list``.
    """
    live: list[Manifest] = []
    if not ws_root.is_dir():
        return live
    for run_dir in sorted(ws_root.iterdir()):
        if not run_dir.is_dir():
            continue
        m = read(run_dir / "manifest.json")
        if m is not None and WorkspaceLock.is_held(run_dir):
            live.append(m)
    return live


def _exit_ambiguous_runs(live: list[Manifest]) -> None:
    """Abort with a list of the live runs sharing one CWD."""
    typer.secho(
        f"{len(live)} live instances share this directory — pick one:",
        fg=typer.colors.YELLOW,
        err=True,
    )
    _print_run_choices(live)
    typer.echo(
        f"Re-run with `{CLI_COMMAND} paths --workspace <storage-dir>` using one "
        f"of the dirs above, or run `{CLI_COMMAND} paths` from inside the "
        "session you want.",
        err=True,
    )
    raise typer.Exit(2)


def _print_run_choices(manifests: list[Manifest]) -> None:
    """List each run's id and storage dir on stderr for disambiguation."""
    for m in manifests:
        typer.echo(f"  {m.run_id}  {m.storage_dir}", err=True)
