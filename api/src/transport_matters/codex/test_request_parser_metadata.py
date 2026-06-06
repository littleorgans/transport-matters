"""parse_codex_request must surface the codex session/thread id for read-back correlation (§7.2).

Codex puts NO top-level ``session_id`` in ``client_metadata``; the id lives nested in
``client_metadata["x-codex-turn-metadata"]`` (a JSON string). Session binding reads
``request_ir.metadata.session_id`` directly, so the parser must resolve it from the turn-metadata.
Verified on a real capture: the turn-metadata ``thread_id`` equals the rollout ``payload.id``
(``019e9553-...``), so this is the id the wire side must correlate on. Without this, every codex
exchange metadata gets ``session_id`` NULL and never joins its transcript.
"""

import json

from transport_matters.codex.request_parser import parse_codex_request
from transport_matters.codex.request_serializer import serialize_codex_request


def _frame(client_metadata: dict[str, object]) -> bytes:
    return json.dumps(
        {
            "type": "response.create",
            "model": "gpt-5-codex",
            "input": "hi",
            "client_metadata": client_metadata,
        }
    ).encode()


def test_session_id_resolved_from_nested_turn_metadata() -> None:
    tid = "019e9553-56f8-71e2-b4b5-d555aac856d9"  # real-capture thread_id == rollout payload.id
    ir = parse_codex_request(
        _frame(
            {
                "x-codex-window-id": f"{tid}:0",
                "x-codex-turn-metadata": json.dumps(
                    {"session_id": tid, "thread_id": tid, "turn_id": ""}
                ),
            }
        )
    )
    assert ir.metadata.session_id == tid


def test_top_level_session_id_wins_when_present() -> None:
    ir = parse_codex_request(
        _frame(
            {
                "session_id": "top-level-1",
                "x-codex-turn-metadata": json.dumps({"session_id": "nested-2"}),
            }
        )
    )
    assert ir.metadata.session_id == "top-level-1"


def test_no_codex_ids_yields_none() -> None:
    ir = parse_codex_request(_frame({"foo": "bar"}))
    assert ir.metadata.session_id is None


def test_resolved_session_id_does_not_leak_top_level_on_reserialize() -> None:
    # Transparency: resolving session_id from the nested turn-metadata must NOT add a top-level
    # session_id to a re-serialized (mutated) frame — the client never sent one (real-capture leak).
    tid = "019e9553-56f8-71e2-b4b5-d555aac856d9"
    cm: dict[str, object] = {
        "x-codex-window-id": f"{tid}:0",
        "x-codex-turn-metadata": json.dumps({"session_id": tid, "thread_id": tid, "turn_id": ""}),
    }
    ir = parse_codex_request(_frame(cm))
    assert ir.metadata.session_id == tid  # resolved for correlation
    reserialized = json.loads(serialize_codex_request(ir))
    assert "session_id" not in reserialized["client_metadata"]  # not duplicated top-level
    assert reserialized["client_metadata"]["x-codex-turn-metadata"] == cm["x-codex-turn-metadata"]
