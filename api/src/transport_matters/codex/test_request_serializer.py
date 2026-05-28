from __future__ import annotations

from transport_matters.codex.request_serializer import _message_content_to_dict
from transport_matters.ir import UnknownBlock


def test_message_content_to_dict_degrades_unknown_block() -> None:
    block = UnknownBlock(raw={"type": "weird_new_block", "data": 1})
    assert _message_content_to_dict("user", block) == {
        "type": "weird_new_block",
        "data": 1,
    }
