import pytest

from transport_matters.ir import (
    InternalRequest,
    InternalResponse,
    Message,
    RequestMetadata,
    SamplingParams,
    SystemPart,
    TextBlock,
    ToolUseBlock,
    UsageStats,
)
from transport_matters.overrides import Override, get_store
from transport_matters.request_pipeline import run_pipeline
from transport_matters.track_manager import get_track_manager


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    get_store().clear()
    get_store().enabled = True
    get_track_manager()._runs.clear()


def _request(
    *,
    provider: str = "anthropic",
    system_text: str = "keep this",
    provider_metadata: dict[str, object] | None = None,
) -> InternalRequest:
    return InternalRequest(
        model="model",
        provider=provider,
        system=[SystemPart(text=system_text)],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text="hello")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(provider_metadata=provider_metadata or {}),
    )


def _response_with_agents(*ids: str) -> InternalResponse:
    return InternalResponse(
        id="resp",
        model="model",
        provider="anthropic",
        usage=UsageStats(),
        content=[
            ToolUseBlock(
                id=agent_id,
                name="Agent",
                input={"subagent_type": f"worker-{index}"},
            )
            for index, agent_id in enumerate(ids)
        ],
    )


async def test_anthropic_subagent_overrides_are_track_scoped() -> None:
    run_id = "run-1"
    agent_a = "toolu_agent_a"
    agent_b = "toolu_agent_b"
    manager = get_track_manager()
    manager.record_exchange(run_id, _request(), _response_with_agents(agent_a, agent_b))
    get_store().upsert(
        Override(kind="system_part_toggle", target="system:0", value=False),
        scope=(run_id, agent_a),
    )

    curated_a, _audit_a, assignment_a = await run_pipeline(
        _request(system_text="agent a"), "flow-a", run_id
    )
    curated_b, _audit_b, assignment_b = await run_pipeline(
        _request(system_text="agent b"), "flow-b", run_id
    )

    assert assignment_a is not None
    assert assignment_a.track_id == agent_a
    assert curated_a.system == []
    assert assignment_b is not None
    assert assignment_b.track_id == agent_b
    assert [part.text for part in curated_b.system] == ["agent b"]


async def test_codex_subagent_overrides_are_track_scoped() -> None:
    run_id = "run-codex"
    get_store().upsert(
        Override(kind="system_part_toggle", target="system:0", value=False),
        scope=(run_id, "codex-a"),
    )

    curated_a, _audit_a, assignment_a = await run_pipeline(
        _request(
            provider="codex",
            system_text="codex a",
            provider_metadata={
                "x-openai-subagent": "1",
                "x-codex-window-id": "codex-a:1.2",
            },
        ),
        "flow-codex-a",
        run_id,
    )
    curated_b, _audit_b, assignment_b = await run_pipeline(
        _request(
            provider="codex",
            system_text="codex b",
            provider_metadata={
                "x-openai-subagent": "1",
                "x-codex-window-id": "codex-b:1.3",
            },
        ),
        "flow-codex-b",
        run_id,
    )

    assert assignment_a is not None
    assert assignment_a.track_id == "codex-a"
    assert curated_a.system == []
    assert assignment_b is not None
    assert assignment_b.track_id == "codex-b"
    assert [part.text for part in curated_b.system] == ["codex b"]


async def test_legacy_pipeline_uses_legacy_scope() -> None:
    get_store().upsert(Override(kind="system_part_toggle", target="system:0", value=False))

    curated, _audit, assignment = await run_pipeline(_request(), "flow-legacy", None)

    assert assignment is None
    assert curated.system == []
