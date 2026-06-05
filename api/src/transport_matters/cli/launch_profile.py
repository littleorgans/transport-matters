"""The managed-launch port (§5.2c): one launch profile per mint-capable CLI.

This is the launch-side counterpart to the read-side :class:`~transport_matters.index.adapters.base.
TranscriptAdapter`. Where the adapter answers *how to read* a CLI's transcript (bind/locate/normalize),
a :class:`LaunchProfile` answers *how to own* a CLI's session at launch:

* **inject** (:meth:`LaunchProfile.client_argv`) — put the owned id into argv (claude:
  ``--session-id <uuid>``; codex: ``resume <uuid>``).
* **prepare** (:meth:`LaunchProfile.prepare`) — compute the owned ``source_descriptor`` up front, and
  pre-seed the transcript if the CLI needs one (claude: deterministic path, no seed; codex: seed the
  minimal ``session_meta`` rollout, then the path).
* **honor passthrough** (:meth:`LaunchProfile.user_supplied_session`) — skip minting when the user
  already pinned a session, so their flag wins (external adoption).

Both ``transport-matters claude`` and ``transport-matters codex`` flow through the SAME
:func:`prepare_managed_session`; a future mint-capable CLI is one new profile + a registry entry, with
ZERO launch-flow duplication. The mint itself (a uuid4 native id) is shared here, not per-profile.

The read-side ``minted``/``session_id`` derivation is its symmetric twin in ``index.ingest.
bind_exchange`` (keyed by provider): the index DAG forbids ``index → cli``, so that half can't live on
this cli-side port. The launch profile owns *ownership at launch*; ``bind_exchange`` owns *what the
owned id means for the session row* (claude: id used directly, ``minted=True``; codex: synth, ``False``).
"""

import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from transport_matters.index.adapters.base import encode_source_descriptor
from transport_matters.index.adapters.claude import claude_transcript_source

from .codex_session import resolve_codex_cli_version, seed_codex_session
from .home_seed import claude_projects_root, codex_sessions_root
from .launch_runtime import (
    CLIENT_NAME_CLAUDE,
    CLIENT_NAME_CODEX,
    managed_child_shell_env_excludes,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime
    from pathlib import Path

# claude flags by which the user pins their own session; if any is present TM does not mint (their
# flag wins, external adoption). ``--session-id`` sets it; ``--resume``/``-r`` and ``--continue``/``-c``
# select an existing one.
_CLAUDE_SESSION_FLAGS = frozenset({"--session-id", "--resume", "-r", "--continue", "-c"})


@dataclass(frozen=True, slots=True)
class ManagedSession:
    """The launcher-owned session for one managed launch: the minted native id + the JSON
    ``source_descriptor`` of the transcript it owns. The id drives argv injection; the descriptor is
    stamped onto the session row (both flow to the addon via the launch env)."""

    native_session_id: str
    source_descriptor: str


class LaunchProfile(ABC):
    """Launch-side anti-corruption layer. One concrete subclass per mint-capable CLI, registered by
    ``cli`` in :data:`PROFILES`. A profile is mint-capable by construction (it implements ``prepare``
    + ``client_argv``); a non-mint CLI simply has no profile and never reaches the managed path."""

    cli: ClassVar[str]

    @abstractmethod
    def prepare(
        self,
        *,
        native_session_id: str,
        client_path: str,
        working_dir: Path,
        home_dir: Path | None,
        env: Mapping[str, str],
        now: datetime,
        write: bool,
    ) -> str:
        """Produce the owned transcript's ``source_descriptor``, pre-seeding it if the CLI needs one.

        ``write=False`` (print-command dry run) computes the descriptor without touching disk."""

    @abstractmethod
    def client_argv(
        self,
        *,
        client_path: str,
        passthrough: Sequence[str],
        native_session_id: str | None,
    ) -> list[str]:
        """Assemble the client argv, injecting the owned id. ``native_session_id is None`` ⇒ external
        adoption / user passthrough: no injection (the user's own flag, if any, stays in passthrough)."""

    @abstractmethod
    def user_supplied_session(self, passthrough: Sequence[str]) -> bool:
        """``True`` when the user already pinned a session (skip minting; honor their flag)."""


class ClaudeLaunchProfile(LaunchProfile):
    cli = CLIENT_NAME_CLAUDE

    def prepare(
        self,
        *,
        native_session_id: str,
        client_path: str,
        working_dir: Path,
        home_dir: Path | None,
        env: Mapping[str, str],
        now: datetime,
        write: bool,
    ) -> str:
        # claude --session-id CREATES the transcript (verified), so there is NO seed: prepare only
        # computes the deterministic descriptor under the home-aware projects root, matching exactly
        # where claude will write. The descriptor path computation is shared with the read-side locate.
        source = claude_transcript_source(
            str(working_dir),
            native_session_id,
            projects_root=claude_projects_root(home_dir, env),
        )
        return encode_source_descriptor(source)

    def client_argv(
        self,
        *,
        client_path: str,
        passthrough: Sequence[str],
        native_session_id: str | None,
    ) -> list[str]:
        session = [] if native_session_id is None else ["--session-id", native_session_id]
        return [client_path, *passthrough, *session]

    def user_supplied_session(self, passthrough: Sequence[str]) -> bool:
        # Match both the space form (``--session-id <uuid>``, a bare flag token) and the equals form
        # (``--session-id=<uuid>``, a single token, which claude accepts): either pins the user's
        # session, so TM must not mint a second id. Splitting on ``=`` normalizes ``--flag=value`` →
        # ``--flag`` and leaves bare tokens unchanged, with no false positive on unrelated ``=`` args.
        return any(arg.split("=", 1)[0] in _CLAUDE_SESSION_FLAGS for arg in passthrough)


class CodexLaunchProfile(LaunchProfile):
    cli = CLIENT_NAME_CODEX

    def prepare(
        self,
        *,
        native_session_id: str,
        client_path: str,
        working_dir: Path,
        home_dir: Path | None,
        env: Mapping[str, str],
        now: datetime,
        write: bool,
    ) -> str:
        # codex resume needs a pre-seeded minimal rollout; seed it under the home-aware sessions root
        # so it lands exactly where the resumed codex appends (§5.2b).
        seed = seed_codex_session(
            native_session_id=native_session_id,
            now=now,
            working_dir=working_dir,
            cli_version=resolve_codex_cli_version(client_path),
            sessions_root=codex_sessions_root(home_dir, env),
            write=write,
        )
        return seed.source_descriptor

    def client_argv(
        self,
        *,
        client_path: str,
        passthrough: Sequence[str],
        native_session_id: str | None,
    ) -> list[str]:
        # The top-level `-c` shell-environment-policy arg precedes the `resume` subcommand, which
        # precedes user passthrough (resume's [PROMPT]/args). No owned id ⇒ no resume (the user's own
        # `resume`, if any, stays in passthrough).
        resume = [] if native_session_id is None else ["resume", native_session_id]
        return [
            client_path,
            *_codex_shell_environment_policy_args(),
            *resume,
            *passthrough,
        ]

    def user_supplied_session(self, passthrough: Sequence[str]) -> bool:
        return "resume" in passthrough


def _codex_shell_environment_policy_args() -> list[str]:
    excluded = ",".join(json.dumps(key) for key in managed_child_shell_env_excludes())
    return ["-c", f"shell_environment_policy.exclude=[{excluded}]"]


PROFILES: dict[str, LaunchProfile] = {
    CLIENT_NAME_CLAUDE: ClaudeLaunchProfile(),
    CLIENT_NAME_CODEX: CodexLaunchProfile(),
}


def prepare_managed_session(
    profile: LaunchProfile,
    *,
    client_path: str | None,
    passthrough: Sequence[str],
    working_dir: Path,
    home_dir: Path | None,
    env: Mapping[str, str],
    now: datetime,
    write: bool,
) -> ManagedSession | None:
    """Mint + prepare the owned session for a managed launch, or ``None`` for external adoption.

    This is the single managed-launch entry point claude and codex (and any future mint-capable CLI)
    share. ``None`` when there is no managed client (proxy-only) or the user already pinned a session.
    A ``None`` result means the launcher emits no owned id/descriptor, so ``bind_exchange`` leaves the
    session ``minted=False`` and the read side falls back to ``locate`` (claude) or stays pending."""
    if client_path is None:
        return None
    if profile.user_supplied_session(passthrough):
        return None
    native_session_id = str(uuid.uuid4())
    descriptor = profile.prepare(
        native_session_id=native_session_id,
        client_path=client_path,
        working_dir=working_dir,
        home_dir=home_dir,
        env=env,
        now=now,
        write=write,
    )
    return ManagedSession(native_session_id=native_session_id, source_descriptor=descriptor)
