from transport_matters.session.artifacts import inline_artifacts_from_ir


def test_inline_artifacts_decode_claude_base64_source() -> None:
    artifacts = inline_artifacts_from_ir(
        {
            "parts": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "aW1hZ2UtYnl0ZXM=",
                    },
                }
            ]
        }
    )

    assert len(artifacts) == 1
    assert artifacts[0].media_type == "image/png"
    assert artifacts[0].data == b"image-bytes"
    assert artifacts[0].ref == {"block_index": 0, "source": {"field": "source.data"}}


def test_inline_artifacts_decode_codex_data_url_source() -> None:
    artifacts = inline_artifacts_from_ir(
        {
            "parts": [
                {
                    "type": "image",
                    "source": {"image_url": "data:image/jpeg;base64,Y29kZXgtaW1hZ2U="},
                }
            ]
        }
    )

    assert len(artifacts) == 1
    assert artifacts[0].media_type == "image/jpeg"
    assert artifacts[0].data == b"codex-image"
    assert artifacts[0].ref == {"block_index": 0, "source": {"field": "source.image_url"}}


def test_inline_artifacts_skip_invalid_base64_source() -> None:
    artifacts = inline_artifacts_from_ir(
        {
            "parts": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "invalid base64",
                    },
                }
            ]
        }
    )

    assert artifacts == []
