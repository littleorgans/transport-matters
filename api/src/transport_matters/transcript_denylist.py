"""Transcript denylist: presentation-only hide rules read from disk.

The transcript read surface reveals every captured record by default; complete
visibility is the product (it beats the CLI terminal precisely because nothing is
hidden). The denylist is the curation lever: an append-only list of dotted-path
predicates the UI applies as a presentation default, hiding matched records behind
a show-hidden toggle. It never strips content from the wire.

The file lives at ``<storage-root>/transcript_denylist.json`` and is read fresh on
every meta request, so an operator edits one file and refreshes the browser with no
frontend rebuild. A missing file is the default state, not an error: the denylist is
empty and the transcript view is unchanged. A malformed file is logged and treated as
empty so a typo can never blank reveal-all.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, ValidationError

from transport_matters.storage_roots import default_storage_root

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

DENYLIST_FILENAME = "transcript_denylist.json"


class TranscriptDenyRule(BaseModel):
    """One presentation hide rule, matched UI-side against an event's native payload.

    ``path`` is a dotted path into the native record (e.g. ``type`` or
    ``attachment.type``). When ``equals`` is set the record is hidden if the value at
    ``path`` equals it; when ``equals`` is omitted or null the record is hidden
    whenever ``path`` resolves to a present value.
    """

    model_config = ConfigDict(frozen=True)

    path: str
    # object (not Any): equals holds whatever JSON scalar the discriminator carries.
    equals: object | None = None


class TranscriptDenylist(BaseModel):
    """The append-only denylist file: a list of hide rules, empty by default."""

    model_config = ConfigDict(frozen=True)

    hide: tuple[TranscriptDenyRule, ...] = ()


def read_transcript_denylist(root: Path | None = None) -> TranscriptDenylist:
    """Read the transcript denylist, defaulting to empty when absent or malformed.

    ``root`` defaults to the backend storage root. The read is uncached so an
    operator's edit is picked up on the next request. Reveal-all is preserved on any
    failure: a missing file is the expected default, and a malformed file is logged
    and treated as empty rather than raised, so curation can never blank the view.
    """
    denylist_path = (root or default_storage_root()) / DENYLIST_FILENAME
    try:
        raw: object = json.loads(denylist_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return TranscriptDenylist()
    except OSError as exc:
        logger.warning("could not read transcript denylist at %s: %s", denylist_path, exc)
        return TranscriptDenylist()
    except json.JSONDecodeError as exc:
        logger.warning("invalid transcript denylist JSON at %s: %s", denylist_path, exc)
        return TranscriptDenylist()
    try:
        return TranscriptDenylist.model_validate(raw)
    except ValidationError as exc:
        logger.warning("invalid transcript denylist at %s: %s", denylist_path, exc)
        return TranscriptDenylist()
