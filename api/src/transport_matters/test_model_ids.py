from __future__ import annotations

from transport_matters.model_ids import denormalise_model, normalise_model


def test_model_id_prefix_helpers_are_idempotent() -> None:
    assert normalise_model("gpt-5-codex", "codex/") == "codex/gpt-5-codex"
    assert normalise_model("codex/gpt-5-codex", "codex/") == "codex/gpt-5-codex"
    assert denormalise_model("codex/gpt-5-codex", "codex/") == "gpt-5-codex"
    assert denormalise_model("gpt-5-codex", "codex/") == "gpt-5-codex"
