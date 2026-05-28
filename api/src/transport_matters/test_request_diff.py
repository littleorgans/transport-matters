from __future__ import annotations

from transport_matters.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    SystemPart,
    TextBlock,
)
from transport_matters.request_diff import (
    outbound_request_if_changed,
    request_unchanged,
)


class _RecordingAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def outbound_request(self, ir: InternalRequest) -> bytes:
        self.calls += 1
        return b"serialized"


def _request(*, system_text: str = "keep this") -> InternalRequest:
    return InternalRequest(
        model="model",
        provider="anthropic",
        system=[SystemPart(text=system_text)],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text="hello")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(),
    )


def test_request_unchanged_true_for_equal_ir() -> None:
    ir = _request()
    assert request_unchanged(ir, ir) is True


def test_request_unchanged_true_for_distinct_but_equal_instances() -> None:
    original = _request(system_text="same")
    curated = _request(system_text="same")
    assert original is not curated
    assert request_unchanged(original, curated) is True


def test_request_unchanged_false_when_pipeline_changes_system() -> None:
    original = _request(system_text="keep this")
    curated = _request(system_text="changed by pipeline")
    assert request_unchanged(original, curated) is False


def test_outbound_request_if_changed_returns_none_when_unchanged() -> None:
    adapter = _RecordingAdapter()
    ir = _request()
    assert outbound_request_if_changed(adapter, ir, ir) is None
    assert adapter.calls == 0


def test_outbound_request_if_changed_serializes_when_changed() -> None:
    adapter = _RecordingAdapter()
    original = _request(system_text="a")
    curated = _request(system_text="b")
    assert outbound_request_if_changed(adapter, original, curated) == b"serialized"
    assert adapter.calls == 1
