"""Block layer: semantic identity, dedup, kind/text determinism, and COALESCE upsert (§13.1)."""

from typing import TYPE_CHECKING

from transport_matters.index.blocks import (
    block_hash,
    block_kind,
    block_text,
    identity_canonical,
    upsert_block,
)
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
from transport_matters.override_audit import canonical_block_json

if TYPE_CHECKING:
    import sqlite3


class TestIdentityCanonical:
    def test_emits_type_first_for_every_kind(self) -> None:
        assert identity_canonical(TextBlock(text="x")).startswith('{"type":"text"')
        assert identity_canonical(ThinkingBlock(text="x")).startswith('{"type":"thinking"')
        assert identity_canonical(SystemPart(text="x")).startswith('{"type":"system"')
        assert identity_canonical(ToolUseBlock(id="i", name="n", input={})).startswith(
            '{"type":"tool_use"'
        )
        tool_def = ToolDef(name="n", description="d", input_schema={})
        assert identity_canonical(tool_def).startswith('{"type":"tool_def"')
        assert identity_canonical(ImageBlock(source={})).startswith('{"type":"image"')
        assert identity_canonical(UnknownBlock(raw={})).startswith('{"type":"unknown"')

    def test_strips_provider_data_and_cache_hint_uniformly(self) -> None:
        assert identity_canonical(
            TextBlock(text="x", provider_data={"k": "v"})
        ) == identity_canonical(TextBlock(text="x"))
        assert "provider_data" not in identity_canonical(
            TextBlock(text="x", provider_data={"k": 1})
        )
        system = SystemPart(text="x", cache_hint={"ttl": 1}, provider_data={"k": 1})
        assert "cache_hint" not in identity_canonical(system)
        assert "provider_data" not in identity_canonical(system)

    def test_recursive_tool_result_strips_nested_provider_data(self) -> None:
        with_pd = ToolResultBlock(
            tool_use_id="i", content=[TextBlock(text="x", provider_data={"k": 1})]
        )
        without = ToolResultBlock(tool_use_id="i", content=[TextBlock(text="x")])
        assert identity_canonical(with_pd) == identity_canonical(without)

    def test_differs_from_char_accounting_canonical(self) -> None:
        block = TextBlock(text="x")
        assert identity_canonical(block) != canonical_block_json(block)
        assert "provider_data" in canonical_block_json(block)  # char encoder keeps it
        assert "provider_data" not in identity_canonical(block)

    def test_system_never_collides_with_text_of_same_text(self) -> None:
        assert identity_canonical(SystemPart(text="x")) != identity_canonical(TextBlock(text="x"))


class TestKindAndText:
    def test_kind_is_pure_function_of_shape(self) -> None:
        assert block_kind(TextBlock(text="x")) == "text"
        assert block_kind(ThinkingBlock(text="x")) == "thinking"
        assert block_kind(SystemPart(text="x")) == "system"
        assert block_kind(ToolDef(name="n", description="d", input_schema={})) == "tool_def"
        assert block_kind(ToolUseBlock(id="i", name="n", input={})) == "tool_use"
        assert block_kind(UnknownBlock(raw={"a": 1})) == "unknown"

    def test_text_projection_excludes_json_envelope(self) -> None:
        assert block_text(TextBlock(text="hello")) == "hello"
        assert block_text(ThinkingBlock(text="pondering")) == "pondering"
        tool_use = ToolUseBlock(id="i", name="bash", input={"command": "git status"})
        assert block_text(tool_use) == "bash git status"
        tool_result = ToolResultBlock(
            tool_use_id="i", content=[TextBlock(text="out-a"), TextBlock(text="out-b")]
        )
        assert block_text(tool_result) == "out-a out-b"
        assert block_text(ToolDef(name="read", description="reads files", input_schema={})) == (
            "read reads files"
        )
        assert block_text(ImageBlock(source={"x": 1})) == ""


class TestUpsertDedup:
    def test_same_content_with_and_without_provider_data_dedups(
        self, conn: sqlite3.Connection
    ) -> None:
        first = upsert_block(conn, TextBlock(text="x", provider_data={"k": "v"}))
        second = upsert_block(conn, TextBlock(text="x"))
        assert first == second
        assert conn.execute("SELECT COUNT(*) FROM block").fetchone()[0] == 1

    def test_kinds_with_identical_text_do_not_collide(self, conn: sqlite3.Connection) -> None:
        ids = {
            upsert_block(conn, TextBlock(text="x")),
            upsert_block(conn, ThinkingBlock(text="x")),
            upsert_block(conn, SystemPart(text="x")),
        }
        assert len(ids) == 3
        assert conn.execute("SELECT COUNT(*) FROM block").fetchone()[0] == 3

    def test_n_tokens_backfills_via_coalesce_without_touching_identity(
        self, conn: sqlite3.Connection
    ) -> None:
        block = TextBlock(text="x")
        first = upsert_block(conn, block)
        assert (
            conn.execute("SELECT n_tokens FROM block WHERE id = ?", (first,)).fetchone()[0] is None
        )
        assert upsert_block(conn, block, n_tokens=7) == first
        kind, text, identity, n_tokens = conn.execute(
            "SELECT kind, text, identity_canonical, n_tokens FROM block WHERE id = ?", (first,)
        ).fetchone()
        assert (kind, text, identity, n_tokens) == ("text", "x", identity_canonical(block), 7)
        upsert_block(conn, block, n_tokens=None)  # a later NULL must not regress
        assert conn.execute("SELECT n_tokens FROM block WHERE id = ?", (first,)).fetchone()[0] == 7

    def test_stored_hash_is_blake2b_of_identity(self, conn: sqlite3.Connection) -> None:
        block = TextBlock(text="x")
        block_id = upsert_block(conn, block)
        stored = conn.execute("SELECT hash FROM block WHERE id = ?", (block_id,)).fetchone()[0]
        assert stored == block_hash(identity_canonical(block))

    def test_inserted_block_is_fts_searchable(self, conn: sqlite3.Connection) -> None:
        upsert_block(conn, TextBlock(text="searchable token"))
        rows = conn.execute(
            "SELECT rowid FROM block_fts WHERE block_fts MATCH 'searchable'"
        ).fetchall()
        assert len(rows) == 1
