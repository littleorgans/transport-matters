"""Content-addressed block layer: semantic identity, hashing, kind/text, and upsert (§3.3).

``identity_canonical`` is a SEPARATE encoder from ``override_audit.canonical_block_json``:
it follows the same type-first ``canonical_*`` discipline but strips ``provider_data`` (and
``SystemPart.cache_hint``) uniformly, so the wire and transcript representations of the same
content hash equal (stream-invariant identity, which is what sharpens the §8.4 pivot). It is
NEVER a call to ``canonical_block_json`` — that would re-admit ``provider_data`` into
identity. Imports ``ir`` + ``canonicalization`` only (DAG core, §12).
"""

from collections.abc import Mapping, Sequence
from hashlib import blake2b
from typing import TYPE_CHECKING, Any  # Any: tool input / image source / unknown raw is schema-free

from transport_matters.canonicalization import canonical_fields, canonical_json, json_string
from transport_matters.ir import (
    ImageBlock,
    SystemPart,
    TextBlock,
    ThinkingBlock,
    ToolDef,
    ToolResultBlock,
    ToolUseBlock,
    UnknownBlock,
)

if TYPE_CHECKING:
    import sqlite3

# Every content unit the index can address: the six wire content blocks plus the two
# request-region parts (system, tool_def). ToolResultBlock's recursive content is itself
# drawn from this set.
IndexablePart = (
    TextBlock
    | ToolUseBlock
    | ToolResultBlock
    | ThinkingBlock
    | ImageBlock
    | UnknownBlock
    | SystemPart
    | ToolDef
)


def identity_canonical(part: IndexablePart) -> str:
    """Return a part's SEMANTIC canonical form: type-first, ``provider_data``/``cache_hint``
    stripped uniformly (§3.3). The blake2b-256 of this string is the block identity."""
    if isinstance(part, TextBlock):
        return canonical_fields(
            [("type", json_string(part.type)), ("text", json_string(part.text))]
        )
    if isinstance(part, ToolUseBlock):
        return canonical_fields(
            [
                ("type", json_string(part.type)),
                ("id", json_string(part.id)),
                ("name", json_string(part.name)),
                ("input", canonical_json(part.input)),
            ]
        )
    if isinstance(part, ToolResultBlock):
        content = "[" + ",".join(identity_canonical(item) for item in part.content) + "]"
        return canonical_fields(
            [
                ("type", json_string(part.type)),
                ("tool_use_id", json_string(part.tool_use_id)),
                ("content", content),
                ("is_error", canonical_json(part.is_error)),
            ]
        )
    if isinstance(part, ThinkingBlock):
        return canonical_fields(
            [("type", json_string(part.type)), ("text", json_string(part.text))]
        )
    if isinstance(part, ImageBlock):
        return canonical_fields(
            [("type", json_string(part.type)), ("source", canonical_json(part.source))]
        )
    if isinstance(part, UnknownBlock):
        return canonical_fields(
            [("type", json_string(part.type)), ("raw", canonical_json(part.raw))]
        )
    if isinstance(part, SystemPart):
        # SystemPart.type is "text" in the IR; identity emits "system" so it never collides
        # with a TextBlock of identical text (§3.3 kind determinism). cache_hint dropped.
        return canonical_fields([("type", json_string("system")), ("text", json_string(part.text))])
    # ToolDef: name/description/input_schema only, so the constant tools array dedups to one
    # block-set across every run and CLI.
    return canonical_fields(
        [
            ("type", json_string("tool_def")),
            ("name", json_string(part.name)),
            ("description", json_string(part.description)),
            ("input_schema", canonical_json(part.input_schema)),
        ]
    )


def block_hash(canonical: str) -> str:
    """Return the blake2b-256 hex digest of an ``identity_canonical`` string (§3.3)."""
    return blake2b(canonical.encode("utf-8"), digest_size=32).hexdigest()


def block_kind(part: IndexablePart) -> str:
    """Return the payload shape (functionally determined by the hash; stored for filtering)."""
    if isinstance(part, SystemPart):
        return "system"
    if isinstance(part, ToolDef):
        return "tool_def"
    return part.type


def block_text(part: IndexablePart) -> str:
    """Return the clean FTS projection (searchable text only; JSON envelope excluded, §3.3)."""
    if isinstance(part, TextBlock | ThinkingBlock | SystemPart):
        return part.text
    if isinstance(part, ToolUseBlock):
        return _join([part.name, _flatten_text(part.input)])
    if isinstance(part, ToolResultBlock):
        return _join([block_text(item) for item in part.content])
    if isinstance(part, ToolDef):
        return _join([part.name, part.description])
    # image, unknown → no useful free-text projection
    return ""


def upsert_block(conn: sqlite3.Connection, part: IndexablePart, n_tokens: int | None = None) -> int:
    """Insert a block (or back-fill ``n_tokens`` on hash conflict) and return its rowid.

    Identity/text columns are frozen forever; only ``n_tokens`` is mutable, filled
    ``NULL → value`` via ``COALESCE`` so a later better estimate never regresses to NULL and
    never touches identity/text (§3.7).
    """
    canonical = identity_canonical(part)
    cur = conn.execute(
        """
        INSERT INTO block (hash, kind, text, identity_canonical, n_tokens)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(hash) DO UPDATE SET n_tokens = COALESCE(excluded.n_tokens, block.n_tokens)
        RETURNING id
        """,
        (block_hash(canonical), block_kind(part), block_text(part), canonical, n_tokens),
    )
    row = cur.fetchone()
    return int(row[0])


def _join(parts: list[str]) -> str:
    return " ".join(part for part in parts if part)


def _flatten_text(value: Any) -> str:  # Any: arbitrary nested tool-input JSON
    """Flatten nested JSON to its string/number leaves for FTS (keys + envelope dropped)."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return ""
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, Mapping):
        return _join([_flatten_text(item) for item in value.values()])
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return _join([_flatten_text(item) for item in value])
    return ""
