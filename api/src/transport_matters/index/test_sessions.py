"""Session synth determinism."""

import uuid

from transport_matters.index.sessions import SESSION_NS, synth_session_id


class TestSynth:
    def test_deterministic_uuid5(self) -> None:
        first = synth_session_id("run1", "codex", "nat-1")
        second = synth_session_id("run1", "codex", "nat-1")
        assert first == second == str(uuid.uuid5(SESSION_NS, "run1|codex|nat-1"))

    def test_distinct_inputs_yield_distinct_ids(self) -> None:
        assert synth_session_id("run1", "codex", "nat-1") != synth_session_id(
            "run1", "codex", "nat-2"
        )
        assert synth_session_id("run1", "codex", "nat-1") != synth_session_id(
            "run2", "codex", "nat-1"
        )
