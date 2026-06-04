"""Tests for the shared low-level canonical-JSON helpers."""

import pytest

from transport_matters.canonicalization import canonical_fields, canonical_json, json_string


class TestCanonicalJson:
    def test_sorts_mapping_keys_by_code_point(self) -> None:
        low, high = chr(0xE000), chr(0x1F600)  # private-use < astral emoji
        assert canonical_json({high: 2, low: 1}) == f'{{"{low}":1,"{high}":2}}'

    def test_rejects_non_finite_numbers(self) -> None:
        with pytest.raises(ValueError, match="non-finite"):
            canonical_json(float("nan"))
        with pytest.raises(ValueError, match="non-finite"):
            canonical_json(float("inf"))

    def test_rejects_unsupported_value(self) -> None:
        with pytest.raises(TypeError, match="Unsupported"):
            canonical_json({1, 2})  # a set is not char-accounting JSON

    def test_nested_sequences_and_mappings(self) -> None:
        assert canonical_json([{"b": 1, "a": [2, 3]}]) == '[{"a":[2,3],"b":1}]'


class TestJsonString:
    def test_escapes_quotes_and_keeps_non_ascii(self) -> None:
        accent = chr(0xE9)  # é
        assert json_string('a"b') == '"a\\"b"'
        assert json_string(accent) == f'"{accent}"'  # ensure_ascii=False keeps the char


class TestCanonicalFields:
    def test_preserves_caller_field_order(self) -> None:
        # canonical_fields does NOT sort; the type-first discipline is the caller's job.
        fields = [("type", '"text"'), ("text", '"x"')]
        assert canonical_fields(fields) == '{"type":"text","text":"x"}'
        assert canonical_fields([("b", "1"), ("a", "2")]) == '{"b":1,"a":2}'

    def test_escapes_keys(self) -> None:
        assert canonical_fields([('a"b', "1")]) == '{"a\\"b":1}'
