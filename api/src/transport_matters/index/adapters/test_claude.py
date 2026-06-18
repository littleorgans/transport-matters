"""claude adapter: normalize the golden fixture per the §5.1 block table; bind/locate (§5.1)."""

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from transport_matters.index.adapters.base import (
    FileTailSource,
    RunContext,
    SessionBinding,
    TurnContext,
)
from transport_matters.index.adapters.claude import ClaudeAdapter, claude_transcript_source
from transport_matters.index.conftest import make_binding
from transport_matters.ir import (
    ImageBlock,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UnknownBlock,
)

if TYPE_CHECKING:
    from transport_matters.index.adapters.base import NormalizedTurn

# Structurally faithful to the real claude_jsonl envelope (verified on real paired samples);
# content is synthetic for repo privacy.
_FIXTURE = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "claude_transcript.jsonl"
_SESSION = "00000000-0000-4000-8000-000000000001"


def _binding() -> SessionBinding:
    return make_binding(_SESSION)


def _normalize_fixture() -> list[NormalizedTurn | None]:
    adapter = ClaudeAdapter()
    binding = _binding()
    out: list[NormalizedTurn | None] = []
    for line in _FIXTURE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ctx = TurnContext(
            binding=binding, source_path=str(_FIXTURE), source_line=len(out), seq=len(out)
        )
        out.append(adapter.normalize(json.loads(line), ctx))
    return out


class TestNormalize:
    def test_skips_non_conversational_records(self) -> None:
        # system, ai-title, file-history-snapshot → None; user/assistant → a turn.
        assert [t is None for t in _normalize_fixture()] == [
            True,
            True,
            True,
            False,
            False,
            False,
            False,
        ]

    def test_user_string_content(self) -> None:
        u1 = next(t for t in _normalize_fixture() if t is not None)
        assert (u1.turn_id, u1.role, u1.parent_id) == ("u1", "user", None)
        assert u1.parts == [TextBlock(text="run the tests")]

    def test_assistant_blocks_with_signature_in_provider_data(self) -> None:
        a1 = [t for t in _normalize_fixture() if t is not None][1]
        assert (a1.role, a1.parent_id, a1.model) == ("assistant", "u1", "claude-sonnet-4-6")
        thinking, text, tool_use = a1.parts
        assert isinstance(thinking, ThinkingBlock) and thinking.provider_data == {
            "signature": "sig-abc"
        }
        assert isinstance(text, TextBlock) and text.text == "Running them now."
        assert isinstance(tool_use, ToolUseBlock) and tool_use.name == "Bash"

    def test_tool_result_image_and_unknown(self) -> None:
        turns = [t for t in _normalize_fixture() if t is not None]
        (tool_result,) = turns[2].parts
        assert isinstance(tool_result, ToolResultBlock) and tool_result.tool_use_id == "toolu_1"
        assert tool_result.content == [TextBlock(text="all green")]
        image, unknown = turns[3].parts
        assert isinstance(image, ImageBlock) and isinstance(unknown, UnknownBlock)
        assert turns[3].is_sidechain is True

    def test_turns_carry_only_content_kinds(self) -> None:
        # never system / tool_def (§4.1.4)
        kinds = {p.type for t in _normalize_fixture() if t is not None for p in t.parts}
        assert kinds <= {"text", "tool_use", "tool_result", "thinking", "image", "unknown"}


class TestBindLocate:
    async def test_bind_uses_native_id_directly(self) -> None:
        run = RunContext(
            run_id="run1",
            cwd="/w",
            workspace_slug="s",
            workspace_hash="h",
            harness="claude",
            started_at="t",
            native_session_id=_SESSION,
        )
        binding = await ClaudeAdapter().bind(run)
        assert (binding.session_id, binding.native_session_id, binding.minted) == (
            _SESSION,
            _SESSION,
            False,
        )

    async def test_bind_requires_native_id(self) -> None:
        run = RunContext(
            run_id="r",
            cwd="/w",
            workspace_slug="s",
            workspace_hash="h",
            harness="claude",
            started_at="t",
        )
        with pytest.raises(ValueError, match="native_session_id"):
            await ClaudeAdapter().bind(run)

    async def test_locate_is_deterministic(self) -> None:
        source = await ClaudeAdapter().locate(_binding())
        assert isinstance(source, FileTailSource)
        assert source.format == "claude_jsonl"
        assert source.path.endswith(f"-w/{_SESSION}.jsonl")  # cwd "/w" → slug "-w"
        assert source.home_dir is None  # no managed home on this binding → native default

    async def test_bind_carries_home_dir(self) -> None:
        # bind propagates the managed --agent-home-dir onto the binding like cwd, so it survives the re-bind
        # and reaches locate (§11.1).
        run = RunContext(
            run_id="run1",
            cwd="/w",
            workspace_slug="s",
            workspace_hash="h",
            harness="claude",
            started_at="t",
            native_session_id=_SESSION,
            home_dir="/managed/.claude",
        )
        binding = await ClaudeAdapter().bind(run)
        assert binding.home_dir == "/managed/.claude"

    async def test_locate_resolves_under_managed_home(self, tmp_path: Path) -> None:
        # External-adoption-under-managed-home: a non-owned claude session whose binding carries the
        # managed home resolves to <home>/projects/<slug>/<sid>.jsonl, NOT ~/.claude/projects (the real
        # correctness gap §11.1 fixes). The descriptor also records the home explicitly.
        binding = _binding().model_copy(update={"home_dir": str(tmp_path)})
        source = await ClaudeAdapter().locate(binding)
        assert isinstance(source, FileTailSource)
        assert source.path == str(tmp_path / "projects" / "-w" / f"{_SESSION}.jsonl")
        assert source.home_dir == str(tmp_path)

    def test_transcript_source_honors_projects_root(self, tmp_path: Path) -> None:
        # The launch `prepare` (§5.2c) and `locate` share ONE path computation. `prepare` passes the
        # home-aware projects root so the owned descriptor matches exactly where claude will write.
        source = claude_transcript_source("/Users/x/proj", "sid-123", projects_root=tmp_path)
        assert isinstance(source, FileTailSource)
        assert source.format == "claude_jsonl"
        assert source.path == str(tmp_path / "-Users-x-proj" / "sid-123.jsonl")

    def test_transcript_source_slugs_every_non_alphanumeric_like_claude(
        self, tmp_path: Path
    ) -> None:
        # claude slugs the cwd by replacing EVERY non-alphanumeric char (/, ., _) with '-', case
        # preserved (VERIFIED on real claude 2.1.165: /private/tmp/tm_slug.probe_AB9 ->
        # -private-tmp-tm-slug-probe-AB9). A naive '/'->'-' leaves the dot/underscore, so the tailer
        # byte-tails a path claude never wrote, caught only on a real run.
        source = claude_transcript_source(
            "/private/tmp/tm_slug.probe_AB9", "sid", projects_root=tmp_path
        )
        assert source.path == str(tmp_path / "-private-tmp-tm-slug-probe-AB9" / "sid.jsonl")
