from transport_matters.codex.response_parser import parse_codex_response_payloads


def test_message_blocks_preserve_empty_text_and_unknown_entries() -> None:
    response = parse_codex_response_payloads(
        [
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-1",
                    "model": "gpt-5-codex",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {"type": "output_text", "text": ""},
                                {"type": "unsupported", "value": 1},
                            ],
                        }
                    ],
                },
            }
        ]
    )

    assert response is not None
    assert response.content[0].type == "text"
    assert response.content[0].text == ""
    assert response.content[1].type == "unknown"
    assert response.content[1].raw == {"type": "unsupported", "value": 1}
