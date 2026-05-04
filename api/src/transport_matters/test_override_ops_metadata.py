"""Tests for override metadata operations."""

from __future__ import annotations

import pytest

from transport_matters.ir import SamplingParams, SystemPart
from transport_matters.overrides import Override, apply_overrides, get_store
from transport_matters.test_override_support import make_ir


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    store = get_store()
    store.clear()
    store.enabled = True


class TestSamplingSet:
    """Sampling overrides update the IR sampling subtree via JSON values."""

    def test_sets_max_tokens(self) -> None:
        ir = make_ir()
        overrides = [
            Override(kind="sampling_set", target="sampling:max_tokens", value="4096")
        ]
        result, audit = apply_overrides(overrides, ir)
        assert result.sampling.max_tokens == 4096
        assert audit.entries[0].applied is True
        assert audit.entries[0].chars_delta == 0

    def test_sets_temperature_float(self) -> None:
        ir = make_ir()
        overrides = [
            Override(kind="sampling_set", target="sampling:temperature", value="0.7")
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.sampling.temperature == 0.7

    def test_sets_temperature_null_unsets_field(self) -> None:
        ir = make_ir().model_copy(
            update={
                "sampling": SamplingParams(max_tokens=1024, temperature=0.9),
            }
        )
        overrides = [
            Override(kind="sampling_set", target="sampling:temperature", value="null")
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.sampling.temperature is None

    def test_sets_top_p_float(self) -> None:
        ir = make_ir()
        overrides = [
            Override(kind="sampling_set", target="sampling:top_p", value="0.95")
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.sampling.top_p == 0.95

    def test_sets_top_k_int(self) -> None:
        ir = make_ir()
        overrides = [Override(kind="sampling_set", target="sampling:top_k", value="40")]
        result, _ = apply_overrides(overrides, ir)
        assert result.sampling.top_k == 40

    def test_sets_stop_sequences_list(self) -> None:
        ir = make_ir()
        overrides = [
            Override(
                kind="sampling_set",
                target="sampling:stop_sequences",
                value='["END", "STOP"]',
            )
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.sampling.stop_sequences == ["END", "STOP"]

    def test_unknown_field_is_unapplied(self) -> None:
        ir = make_ir()
        overrides = [
            Override(kind="sampling_set", target="sampling:nonsense", value="1")
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.sampling == ir.sampling

    def test_malformed_json_is_unapplied(self) -> None:
        ir = make_ir()
        overrides = [
            Override(
                kind="sampling_set", target="sampling:temperature", value="not-json"
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.sampling == ir.sampling

    def test_wrong_type_for_field_is_unapplied(self) -> None:
        ir = make_ir()
        overrides = [
            Override(kind="sampling_set", target="sampling:max_tokens", value='"four"')
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.sampling == ir.sampling

    def test_max_tokens_rejects_bool(self) -> None:
        ir = make_ir()
        overrides = [
            Override(kind="sampling_set", target="sampling:max_tokens", value="true")
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.sampling == ir.sampling

    def test_chars_accounting_is_untouched(self) -> None:
        ir = make_ir(system=[SystemPart(type="text", text="hello")])
        overrides = [
            Override(kind="sampling_set", target="sampling:max_tokens", value="2048")
        ]
        _, audit = apply_overrides(overrides, ir)
        assert audit.chars_before == audit.chars_after


class TestProviderExtrasSet:
    """provider_extras_set merges or deletes keys in provider_extras."""

    def test_sets_thinking_dict(self) -> None:
        ir = make_ir()
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking",
                value='{"type": "enabled", "budget_tokens": 10000}',
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert result.provider_extras["thinking"] == {
            "type": "enabled",
            "budget_tokens": 10000,
        }
        assert audit.entries[0].applied is True
        assert audit.entries[0].chars_delta == 0

    def test_null_value_deletes_key(self) -> None:
        ir = make_ir().model_copy(
            update={"provider_extras": {"thinking": {"type": "enabled"}}}
        )
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking",
                value="null",
            )
        ]
        result, _ = apply_overrides(overrides, ir)
        assert "thinking" not in result.provider_extras

    def test_merges_alongside_existing_keys(self) -> None:
        ir = make_ir().model_copy(update={"provider_extras": {"foo": "bar"}})
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking",
                value='{"type": "enabled"}',
            )
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.provider_extras["foo"] == "bar"
        assert result.provider_extras["thinking"] == {"type": "enabled"}

    def test_malformed_json_is_unapplied(self) -> None:
        ir = make_ir()
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking",
                value="{not-json",
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.provider_extras == ir.provider_extras

    def test_empty_key_is_unapplied(self) -> None:
        ir = make_ir()
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:",
                value='"x"',
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.provider_extras == ir.provider_extras

    def test_batch_with_sampling_thinking_toggle(self) -> None:
        ir = make_ir().model_copy(
            update={
                "sampling": SamplingParams(
                    max_tokens=1024, temperature=0.7, top_p=0.9, top_k=40
                ),
            }
        )
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking",
                value='{"type": "enabled", "budget_tokens": 10000}',
            ),
            Override(kind="sampling_set", target="sampling:temperature", value="null"),
            Override(kind="sampling_set", target="sampling:top_p", value="null"),
            Override(kind="sampling_set", target="sampling:top_k", value="null"),
        ]
        result, audit = apply_overrides(overrides, ir)
        assert result.sampling.temperature is None
        assert result.sampling.top_p is None
        assert result.sampling.top_k is None
        assert result.provider_extras["thinking"] == {
            "type": "enabled",
            "budget_tokens": 10000,
        }
        assert all(entry.applied for entry in audit.entries)


class TestProviderExtrasNestedPath:
    """Dotted targets reach nested provider_extras keys and prune on clear."""

    def test_sets_nested_value(self) -> None:
        ir = make_ir()
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking.display",
                value='"summarized"',
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert result.provider_extras == {"thinking": {"display": "summarized"}}
        assert audit.entries[0].applied is True

    def test_sets_nested_preserves_siblings(self) -> None:
        ir = make_ir().model_copy(
            update={
                "provider_extras": {
                    "thinking": {"type": "enabled", "budget_tokens": 8000},
                }
            }
        )
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking.display",
                value='"summarized"',
            )
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.provider_extras["thinking"] == {
            "type": "enabled",
            "budget_tokens": 8000,
            "display": "summarized",
        }

    def test_sets_deep_path_creates_intermediates(self) -> None:
        ir = make_ir()
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:output_config.effort",
                value='"high"',
            )
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.provider_extras == {"output_config": {"effort": "high"}}

    def test_nested_clear_prunes_empty_parent(self) -> None:
        ir = make_ir().model_copy(
            update={"provider_extras": {"output_config": {"effort": "low"}}}
        )
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:output_config.effort",
                value="null",
            )
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.provider_extras == {}

    def test_nested_clear_preserves_parent_with_siblings(self) -> None:
        ir = make_ir().model_copy(
            update={
                "provider_extras": {
                    "thinking": {"type": "enabled", "display": "summarized"},
                }
            }
        )
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking.display",
                value="null",
            )
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.provider_extras == {"thinking": {"type": "enabled"}}

    def test_nested_clear_recursive_cascade(self) -> None:
        ir = make_ir().model_copy(update={"provider_extras": {"a": {"b": {"c": 1}}}})
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:a.b.c",
                value="null",
            )
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.provider_extras == {}

    def test_nested_clear_cascade_stops_at_sibling(self) -> None:
        ir = make_ir().model_copy(
            update={"provider_extras": {"a": {"b": {"c": 1}, "d": 2}}}
        )
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:a.b.c",
                value="null",
            )
        ]
        result, _ = apply_overrides(overrides, ir)
        assert result.provider_extras == {"a": {"d": 2}}

    def test_nested_clear_on_missing_path_is_idempotent(self) -> None:
        ir = make_ir()
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking.display",
                value="null",
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert result.provider_extras == {}
        assert audit.entries[0].applied is True

    def test_rejects_dunder_segment(self) -> None:
        ir = make_ir()
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking.__proto__",
                value='"x"',
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.provider_extras == ir.provider_extras

    def test_rejects_constructor_segment(self) -> None:
        ir = make_ir()
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:output_config.constructor",
                value='"x"',
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.provider_extras == ir.provider_extras

    def test_rejects_empty_segment(self) -> None:
        ir = make_ir()
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking..display",
                value='"x"',
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.provider_extras == ir.provider_extras

    def test_rejects_non_dict_intermediate_on_set(self) -> None:
        ir = make_ir().model_copy(update={"provider_extras": {"thinking": "plain"}})
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking.display",
                value='"summarized"',
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.provider_extras == {"thinking": "plain"}

    def test_rejects_non_dict_intermediate_on_clear(self) -> None:
        ir = make_ir().model_copy(update={"provider_extras": {"thinking": "plain"}})
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking.display",
                value="null",
            )
        ]
        result, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert result.provider_extras == {"thinking": "plain"}

    def test_nested_does_not_mutate_original_ir(self) -> None:
        ir = make_ir().model_copy(
            update={"provider_extras": {"thinking": {"type": "enabled"}}}
        )
        original_thinking = ir.provider_extras["thinking"]
        overrides = [
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking.display",
                value='"summarized"',
            )
        ]
        apply_overrides(overrides, ir)
        assert ir.provider_extras["thinking"] == {"type": "enabled"}
        assert ir.provider_extras["thinking"] is original_thinking
