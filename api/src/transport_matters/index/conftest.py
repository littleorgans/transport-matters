"""Shared fixtures for the surviving transcript adapter tests."""

from transport_matters.index.adapters.base import SessionBinding


def make_binding(
    session_id: str,
    *,
    provider: str = "anthropic",
    cli: str | None = "claude",
    run_id: str = "run1",
    cwd: str = "/w",
    workspace_slug: str = "slug",
    workspace_hash: str = "hash",
    started_at: str = "t",
    native_session_id: str | None = None,
    minted: bool = False,
) -> SessionBinding:
    """The one canonical ``SessionBinding`` factory for adapter and tailer tests."""
    return SessionBinding(
        session_id=session_id,
        provider=provider,
        run_id=run_id,
        cwd=cwd,
        workspace_slug=workspace_slug,
        workspace_hash=workspace_hash,
        started_at=started_at,
        cli=cli,
        native_session_id=native_session_id if native_session_id is not None else session_id,
        minted=minted,
    )
