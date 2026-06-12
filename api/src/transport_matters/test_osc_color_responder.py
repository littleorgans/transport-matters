from transport_matters.osc_color_responder import (
    OSC_BACKGROUND_REPLY,
    OSC_FOREGROUND_REPLY,
    OscColorResponder,
)


def test_answers_background_query_with_bel_terminator() -> None:
    responder = OscColorResponder()
    assert responder.replies_for(b"\x1b]11;?\x07") == [OSC_BACKGROUND_REPLY]


def test_answers_both_queries_in_one_chunk_in_order() -> None:
    responder = OscColorResponder()
    chunk = b"boot\x1b]10;?\x1b\\middle\x1b]11;?\x07tail"
    assert responder.replies_for(chunk) == [OSC_FOREGROUND_REPLY, OSC_BACKGROUND_REPLY]


def test_answers_a_query_split_across_chunks() -> None:
    responder = OscColorResponder()
    assert responder.replies_for(b"output\x1b]11") == []
    assert responder.replies_for(b";?\x07more") == [OSC_BACKGROUND_REPLY]


def test_never_answers_the_same_query_twice() -> None:
    # A completed match must not survive into the carry and re-match.
    responder = OscColorResponder()
    assert responder.replies_for(b"\x1b]11;?\x07") == [OSC_BACKGROUND_REPLY]
    assert responder.replies_for(b"") == []
    assert responder.replies_for(b"quiet output") == []


def test_ignores_non_query_osc_and_plain_output() -> None:
    responder = OscColorResponder()
    # A set-title OSC and an actual OSC 11 *response* are not queries.
    chunk = b"\x1b]0;title\x07\x1b]11;rgb:1111/2222/3333\x1b\\plain"
    assert responder.replies_for(chunk) == []


def test_each_repeated_query_gets_its_own_reply() -> None:
    # Codex re-queries on terminal focus events; every occurrence is answered.
    responder = OscColorResponder()
    assert responder.replies_for(b"\x1b]11;?\x07\x1b]11;?\x07") == [
        OSC_BACKGROUND_REPLY,
        OSC_BACKGROUND_REPLY,
    ]
