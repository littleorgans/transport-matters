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
        # An OLD descriptor predating slice 8b-ii has no ``home_dir`` → decodes to None (graceful, no
        # error): the additive optional field needs no ADAPTERS_VERSION bump / no drop+rebuild (§11.1).
        assert decoded.home_dir is None

    def test_home_dir_round_trips(self) -> None:
        # The managed --agent-home-dir is carried EXPLICITLY on the descriptor (not just baked into the path)
        # so a §10.5 rebuild re-resolves the transcript root without the live launch env (§11.1).
        source = FileTailSource(
            path="/managed/.claude/projects/-w/sid.jsonl",
            format="claude_jsonl",
            home_dir="/managed/.claude",
        )
        decoded = decode_source_descriptor(encode_source_descriptor(source))
        assert isinstance(decoded, FileTailSource)
        assert decoded == source
        assert decoded.home_dir == "/managed/.claude"
