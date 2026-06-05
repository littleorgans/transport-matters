"""Adapter base contract: the source_descriptor codec used by the managed-mint seam (§7.3)."""

from transport_matters.index.adapters.base import (
    FileTailSource,
    PullSource,
    decode_source_descriptor,
    encode_source_descriptor,
)


class TestSourceDescriptorCodec:
    def test_file_tail_round_trips(self) -> None:
        source = FileTailSource(
            path="/home/u/.codex/sessions/2026/06/05/rollout-x.jsonl", format="codex_rollout"
        )
        decoded = decode_source_descriptor(encode_source_descriptor(source))
        assert (
            decoded == source
        )  # value-equal: the launcher encodes, the tailer decodes the SAME source

    def test_pull_source_round_trips_via_discriminator(self) -> None:
        # The descriptor is a discriminated TranscriptSource, so a PullSource survives too (§5.4).
        source = PullSource(
            ref="ses_1", mechanism="export", command=["opencode", "export", "ses_1"]
        )
        decoded = decode_source_descriptor(encode_source_descriptor(source))
        assert isinstance(decoded, PullSource)
        assert decoded == source

    def test_decode_selects_file_tail_by_kind(self) -> None:
        decoded = decode_source_descriptor(
            '{"kind":"file_tail","path":"/p","format":"codex_rollout"}'
        )
        assert isinstance(decoded, FileTailSource)
        assert decoded.path == "/p"
        assert decoded.encoding == "utf-8"  # default applied
