"""Answers terminal OSC color queries on behalf of absent viewers.

Captured runs spawn their CLI before any xterm viewer attaches, so the CLI's
startup OSC 10/11 query (foreground/background color) goes unanswered. Codex
gives that query a ~100ms window and silently degrades styling that depends on
it: the user-prompt background bands are blend(white, terminal_bg, 0.12) and
are suppressed forever when terminal_bg stays unknown, resurfacing only after
a terminal focus event triggers a requery. The bridge sees the bytes either
way, so this module scans PTY output for the queries and writes the reply into
PTY input, exactly like an attached terminal would, inside the window.

The reply colors mirror what the canvas xterm reports today: the pane theme
background is transparent, which xterm reports as pure black, and the
foreground tracks --color-txt. Keeping the values identical makes a late
xterm answer (attached viewers also respond) idempotent rather than a
flicker. Theme-fed values belong here when that slice lands.
"""

from __future__ import annotations

import re
from typing import Final

OSC_FOREGROUND_REPLY: Final = b"\x1b]10;rgb:dcdc/dcdc/dcdc\x1b\\"
OSC_BACKGROUND_REPLY: Final = b"\x1b]11;rgb:0000/0000/0000\x1b\\"

# OSC 10 = foreground, OSC 11 = background; "?" asks, BEL or ST terminates.
_QUERY: Final = re.compile(rb"\x1b\](1[01]);\?(?:\x07|\x1b\\)")
_REPLIES: Final = {b"10": OSC_FOREGROUND_REPLY, b"11": OSC_BACKGROUND_REPLY}
# The longest query is 8 bytes; carrying 7 re-joins any split across reads.
_CARRY_BYTES: Final = 7


class OscColorResponder:
    """Stateful scanner: one instance per PTY, fed every output chunk."""

    def __init__(self) -> None:
        self._carry = b""

    def replies_for(self, chunk: bytes) -> list[bytes]:
        """Replies owed for the queries completed within this chunk.

        A small tail is carried between calls so a query split across two
        reads still matches; the carry never re-spans a completed match, so
        no query is answered twice.
        """
        window = self._carry + chunk
        replies: list[bytes] = []
        last_end = 0
        for match in _QUERY.finditer(window):
            replies.append(_REPLIES[match.group(1)])
            last_end = match.end()
        self._carry = window[max(last_end, len(window) - _CARRY_BYTES) :]
        return replies
