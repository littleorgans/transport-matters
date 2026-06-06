"""Tailer: crash-safe complete-record iterate, poll/submit, registration, live event (§13.2)."""

import json
from typing import TYPE_CHECKING

from transport_matters.index.adapters.base import (
    FileTailSource,
    SessionBinding,
    encode_source_descriptor,
)
from transport_matters.index.adapters.claude import ClaudeAdapter
from transport_matters.index.adapters.codex import CodexAdapter
from transport_matters.index.conftest import make_binding
from transport_matters.index.sessions import synth_session_id
from transport_matters.index.tailer import (
    TailCursor,
    TranscriptTailer,
    iter_complete_records,
    register_session_cursor,
)
from transport_matters.session.ingest import EventWrite, build_event

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_SESSION = "00000000-0000-4000-8000-000000000001"
_RUN = "run1"


def _codex_session_meta(native: str) -> str:
    return json.dumps(
        {
            "type": "session_meta",
            "payload": {
                "id": native,
                "timestamp": "2026-06-05T10:00:00.000Z",
                "cwd": "/w",
                "originator": "codex-tui",
                "cli_version": "0.137.0",
            },
        }
    )


def _codex_response_item(text: str) -> str:
    return json.dumps(
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            },
        }
    )


def _codex_wire_binding(native: str, descriptor: str | None) -> SessionBinding:
    """A codex wire binding as ``bind_exchange`` resolves it: synth session_id, cli unset on the
    wire side, ``source_descriptor`` present only for the session the launcher owns (§5.2b)."""
    return SessionBinding(
        session_id=synth_session_id(_RUN, "codex", native),
        provider="codex",
        run_id=_RUN,
        cwd="/w",
        workspace_slug="s",
        workspace_hash="h",
        started_at="t",
        cli=None,
        native_session_id=native,
        minted=False,
        source_descriptor=descriptor,
    )


def _claude_wire_binding(session_id: str, descriptor: str | None) -> SessionBinding:
    """A claude managed wire binding as ``bind_exchange`` resolves it (§5.2c): ``minted=True``,
    session_id == the native id used directly, ``source_descriptor`` = the owned transcript path."""
    return SessionBinding(
        session_id=session_id,
        provider="anthropic",
        run_id=_RUN,
        cwd="/w",
        workspace_slug="s",
        workspace_hash="h",
        started_at="t",
        cli="claude",
        native_session_id=session_id,
        minted=True,
        source_descriptor=descriptor,
    )


def _binding(cwd: str = "/w") -> SessionBinding:
    return make_binding(_SESSION, cwd=cwd, workspace_slug="s", workspace_hash="h")


def _user_line(uuid: str, text: str) -> str:
    return json.dumps(
        {
            "type": "user",
            "uuid": uuid,
            "parentUuid": None,
            "sessionId": _SESSION,
            "isSidechain": False,
            "timestamp": "2026-06-05T12:00:00Z",
            "message": {"role": "user", "content": text},
        }
    )


def _cursor(path: str) -> TailCursor:
    return TailCursor(
        binding=_binding(),
        source=FileTailSource(path=path, format="claude_jsonl"),
        adapter=ClaudeAdapter(),
    )


def _event_tailer(
    submitted: list[EventWrite],
    snapshot: Callable[[str, int, bytes], None] | None = None,
) -> TranscriptTailer:
    def submit_batch(_binding: SessionBinding, events: list[EventWrite]) -> None:
        submitted.extend(events)

    return TranscriptTailer(
        build_record=build_event,
        submit_batch=submit_batch,
        snapshot=snapshot,
    )


class TestIterateSeam:
    def test_complete_records_only_leaves_trailing_partial(self) -> None:
        data = b'{"a":1}\n{"b":2}\n{"partial'
        records, consumed = iter_complete_records(data)
        assert records == [{"a": 1}, {"b": 2}]
        assert consumed == data.rfind(b"\n") + 1  # past the LAST newline; partial NOT consumed

    def test_no_newline_consumes_nothing(self) -> None:
        assert iter_complete_records(b'{"a":1}') == ([], 0)

    def test_skips_malformed_complete_lines(self) -> None:
        records, _ = iter_complete_records(b'{"ok":1}\nnot json\n{"ok":2}\n')
        assert records == [{"ok": 1}, {"ok": 2}]

    def test_shared_seam_drives_closed_file_backfill(self) -> None:
        # The SAME fn serves a closed-file backfill pass: a file ending in \n yields all records.
        data = b'{"a":1}\n{"b":2}\n'
        records, consumed = iter_complete_records(data)
        assert records == [{"a": 1}, {"b": 2}]
        assert consumed == len(data)


class TestTailerPoll:
    def test_poll_submits_complete_and_leaves_partial(self, tmp_path: Path) -> None:
        path = tmp_path / "t.jsonl"
        path.write_text(_user_line("u1", "hi") + "\n" + '{"type":"user","uuid":"u2"')
        submitted: list[EventWrite] = []
        tailer = _event_tailer(submitted)
        tailer.register(_cursor(str(path)))
        tailer.poll()
        assert [write.event.native_turn_id for write in submitted] == [
            "u1"
        ]  # only the complete record

        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                f',"parentUuid":null,"sessionId":"{_SESSION}","isSidechain":false,'
                '"timestamp":"t","message":{"role":"user","content":"x"}}\n'
            )
        tailer.poll()
        assert [write.event.native_turn_id for write in submitted] == [
            "u1",
            "u2",
        ]  # partial completed → consumed

    def test_register_is_idempotent(self, tmp_path: Path) -> None:
        submitted: list[EventWrite] = []
        tailer = _event_tailer(submitted)
        path = tmp_path / "t.jsonl"
        path.write_text(_user_line("u1", "hi") + "\n")
        cursor = _cursor(str(path))
        tailer.register(cursor)
        tailer.register(cursor)  # idempotent on session_id
        tailer.poll()
        assert [write.event.native_turn_id for write in submitted] == [
            "u1"
        ]  # one cursor, one submit
        tailer.unregister(_SESSION)
        tailer.poll()
        assert len(submitted) == 1  # unregistered → no further submits

    def test_cursor_state_advances_only_after_submit_success(self, tmp_path: Path) -> None:
        path = tmp_path / "t.jsonl"
        path.write_text(_user_line("u1", "hi") + "\n")
        submitted: list[EventWrite] = []
        calls: list[int] = []

        def submit_batch(_binding: SessionBinding, events: list[EventWrite]) -> None:
            calls.append(len(events))
            if len(calls) == 1:
                raise RuntimeError("database unavailable")
            submitted.extend(events)

        tailer = TranscriptTailer(build_record=build_event, submit_batch=submit_batch)
        tailer.register(_cursor(str(path)))

        tailer.poll()
        (cursor,) = tailer._snapshot()
        assert calls == [1]
        assert submitted == []
        assert cursor.byte_offset == 0
        assert cursor.seq == 0
        assert cursor.parent_id is None
        assert cursor.stat_signature is None

        tailer.poll()
        assert calls == [1, 1]
        assert [write.event.native_turn_id for write in submitted] == ["u1"]
        assert cursor.byte_offset == len(path.read_bytes())
        assert cursor.seq == 1
        assert cursor.parent_id == "u1"
        assert cursor.stat_signature is not None


class TestSnapshotTee:
    """Slice 8b-i: the tailer tees the consumed transcript bytes into the injected snapshot writer."""

    def test_poll_tees_consumed_bytes_at_cursor_offset(self, tmp_path: Path) -> None:
        # The tee mirrors the CLI cursor: one call per poll with (session_id, start_offset, consumed
        # bytes), the SAME bytes iter_complete_records consumed, the trailing partial excluded.
        path = tmp_path / "t.jsonl"
        first = _user_line("u1", "hi") + "\n"
        path.write_text(first + '{"type":"user","uuid":"u2"')  # complete record + a partial
        tees: list[tuple[str, int, bytes]] = []
        submitted: list[EventWrite] = []
        tailer = _event_tailer(
            submitted,
            snapshot=lambda sid, off, data: tees.append((sid, off, data)),
        )
        tailer.register(_cursor(str(path)))

        tailer.poll()
        assert tees == [(_SESSION, 0, first.encode())]  # consumed prefix only, NOT the partial

        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                f',"parentUuid":null,"sessionId":"{_SESSION}","isSidechain":false,'
                '"timestamp":"t","message":{"role":"user","content":"x"}}\n'
            )
        tailer.poll()
        # second tee starts exactly where the first ended (no overlap, no gap) → byte-faithful copy
        assert tees[0][1] + len(tees[0][2]) == tees[1][1]
        assert b"".join(data for _, _, data in tees) == path.read_bytes()

    def test_tees_non_conversational_records_normalize_drops(self, tmp_path: Path) -> None:
        # session_meta is non-conversational: normalize returns None (no job), but the snapshot MUST
        # still capture it byte-faithfully so a future normalize change can re-derive it (§5.2).
        native = "019e0000-0000-7000-8000-00000000c0de"
        path = tmp_path / "rollout.jsonl"
        meta_line = _codex_session_meta(native) + "\n"
        path.write_text(meta_line)
        tees: list[tuple[str, int, bytes]] = []
        submitted: list[EventWrite] = []
        tailer = _event_tailer(
            submitted,
            snapshot=lambda sid, off, data: tees.append((sid, off, data)),
        )
        tailer.register(
            TailCursor(
                binding=_codex_wire_binding(native, None),
                source=FileTailSource(path=str(path), format="codex_rollout"),
                adapter=CodexAdapter(),
            )
        )

        tailer.poll()
        assert [(write.event.kind, write.event.raw["type"]) for write in submitted] == [
            ("meta", "session_meta")
        ]
        assert b"".join(data for _, _, data in tees) == meta_line.encode()

    def test_snapshot_failure_does_not_advance_and_retries_next_poll(self, tmp_path: Path) -> None:
        # The tee is coupled to the cursor advance: a snapshot raise must NOT advance byte_offset AND
        # must NOT set stat_signature, so the very next poll RETRIES even though the CLI file is
        # unchanged (no waiting for the file to grow). Keeps tier-1 snapshot + tier-2 turns consistent.
        path = tmp_path / "t.jsonl"
        path.write_text(_user_line("u1", "hi") + "\n")
        calls: list[int] = []

        def failing_snapshot(_sid: str, _off: int, _data: bytes) -> None:
            calls.append(1)
            raise OSError("disk full")

        submitted: list[EventWrite] = []
        tailer = _event_tailer(submitted, snapshot=failing_snapshot)
        tailer.register(_cursor(str(path)))

        tailer.poll()  # snapshot raises → poll() swallows + logs
        tailer.poll()  # CLI file UNCHANGED → must retry, not skip at the stat guard

        assert len(calls) == 2  # retried on the unchanged file
        assert submitted == []  # ingest never ran because snapshot raised first
        (cursor,) = tailer._snapshot()
        assert cursor.byte_offset == 0  # not advanced past un-snapshotted bytes
        assert cursor.stat_signature is None  # not advanced → this is what re-enables the retry

    def test_unchanged_file_after_success_is_not_reread(self, tmp_path: Path) -> None:
        # The stat-skip optimization must survive moving stat_signature: after a SUCCESSFUL poll an
        # unchanged re-poll does not re-tee (stat_signature is set once the poll fully succeeds).
        path = tmp_path / "t.jsonl"
        path.write_text(_user_line("u1", "hi") + "\n")
        tees: list[tuple[str, int, bytes]] = []
        tailer = _event_tailer([], snapshot=lambda s, o, d: tees.append((s, o, d)))
        tailer.register(_cursor(str(path)))
        tailer.poll()
        tailer.poll()  # unchanged → skipped at the stat guard, not re-teed
        assert len(tees) == 1

    def test_poll_without_snapshot_callback_is_safe(self, tmp_path: Path) -> None:
        path = tmp_path / "t.jsonl"
        path.write_text(_user_line("u1", "hi") + "\n")
        submitted: list[EventWrite] = []
        tailer = _event_tailer(submitted)  # no snapshot injected (default None)
        tailer.register(_cursor(str(path)))
        tailer.poll()
        assert [write.event.native_turn_id for write in submitted] == ["u1"]  # tier-2 unaffected


class TestRegisterCursor:
    async def test_register_session_cursor_locates_and_registers(self) -> None:
        tailer = TranscriptTailer(lambda _job: None)
        await register_session_cursor(tailer, ClaudeAdapter(), _binding(cwd="/w"))
        cursors = tailer._snapshot()
        assert len(cursors) == 1
        source = cursors[0].source
        assert isinstance(source, FileTailSource)
        assert source.path.endswith(f"-w/{_SESSION}.jsonl")
        assert cursors[0].byte_offset == 0  # catches turns written before registration

    async def test_external_adoption_under_managed_home_locates_under_home(
        self, tmp_path: Path
    ) -> None:
        # External-adoption-under-managed-home (§11.1): a claude wire binding with NO owned descriptor
        # but a managed ``home_dir`` re-binds through RunContext (which carries home_dir like cwd), so
        # ``locate`` resolves the transcript under <home>/projects, NOT ~/.claude, and the cursor
        # binding keeps the home. This is the real correctness gap the locate fix closes.
        wire = _binding(cwd="/w").model_copy(update={"home_dir": str(tmp_path)})
        tailer = TranscriptTailer(lambda _job: None)
        await register_session_cursor(tailer, ClaudeAdapter(), wire)
        (cursor,) = tailer._snapshot()
        assert cursor.binding.home_dir == str(tmp_path)  # survived the re-bind
        assert isinstance(cursor.source, FileTailSource)
        assert cursor.source.path == str(tmp_path / "projects" / "-w" / f"{_SESSION}.jsonl")

    async def test_claude_managed_rebind_preserves_minted_and_owned_descriptor(
        self, tmp_path: Path
    ) -> None:
        # Managed-mint (§5.2c): claude's wire binding is minted=True with the OWNED deterministic
        # descriptor. The re-bind goes through ClaudeAdapter.bind, which returns minted=False (it
        # cannot know the id was TM-injected), so register_session_cursor MUST preserve the wire
        # side's authoritative minted + descriptor onto the cursor binding. Otherwise the transcript
        # path's session-row upsert (minted = excluded.minted, last-writer-wins) clobbers minted back
        # to 0 once a turn lands, breaking the §5.5 row and regression (f).
        session = "019e0000-0000-7000-8000-00000000beef"
        transcript = tmp_path / "owned.jsonl"
        descriptor = encode_source_descriptor(
            FileTailSource(path=str(transcript), format="claude_jsonl")
        )
        tailer = TranscriptTailer(lambda _job: None)
        await register_session_cursor(
            tailer, ClaudeAdapter(), _claude_wire_binding(session, descriptor)
        )
        (cursor,) = tailer._snapshot()
        assert cursor.binding.minted is True  # NOT clobbered to False by the re-bind
        assert cursor.binding.source_descriptor == descriptor
        source = cursor.source
        assert isinstance(source, FileTailSource)
        assert source.path == str(
            transcript
        )  # tails the OWNED path, not locate's ~/.claude default

    async def test_codex_rebind_converges_and_uses_owned_descriptor(self, tmp_path: Path) -> None:
        # The transcript binding is RE-DERIVED through the adapter (bind() + RunContext go LIVE,
        # audit #2): for codex read-back the synth session_id must reproduce the wire side's (§7.2),
        # and the cursor binds the codex adapter's cli. Managed-mint (§5.2b): the source is the OWNED
        # rollout from the wire binding's source_descriptor, NOT a ~/.codex glob (the glob is gone).
        native = "019e0000-0000-7000-8000-00000000c0de"
        rollout = tmp_path / f"rollout-2026-06-05T10-00-00-{native}.jsonl"
        descriptor = encode_source_descriptor(
            FileTailSource(path=str(rollout), format="codex_rollout")
        )
        wire_binding = _codex_wire_binding(native, descriptor)
        tailer = TranscriptTailer(lambda _job: None)
        await register_session_cursor(tailer, CodexAdapter(), wire_binding)
        (cursor,) = tailer._snapshot()
        assert cursor.binding.session_id == wire_binding.session_id  # convergence: same synth id
        assert cursor.binding.cli == "codex"  # adapter-derived (was None on the wire binding)
        assert isinstance(cursor.source, FileTailSource)
        assert cursor.source.format == "codex_rollout"
        assert cursor.source.path == str(rollout)  # the OWNED path, byte-for-byte (no glob)

    async def test_owned_descriptor_cursor_tails_deterministically(self, tmp_path: Path) -> None:
        # Regression (a): seed the minimal rollout, register the cursor from the descriptor, append
        # one response_item, poll → EXACTLY one transcript job, tailed from the exact owned path.
        native = "019e0000-0000-7000-8000-0000000000aa"
        rollout = tmp_path / f"rollout-2026-06-05T10-00-00-{native}.jsonl"
        rollout.write_text(_codex_session_meta(native) + "\n", encoding="utf-8")
        descriptor = encode_source_descriptor(
            FileTailSource(path=str(rollout), format="codex_rollout")
        )
        submitted: list[EventWrite] = []
        tailer = _event_tailer(submitted)
        await register_session_cursor(
            tailer, CodexAdapter(), _codex_wire_binding(native, descriptor)
        )

        tailer.poll()
        assert [(write.event.kind, write.event.raw["type"]) for write in submitted] == [
            ("meta", "session_meta")
        ]
        with rollout.open("a", encoding="utf-8") as handle:
            handle.write(_codex_response_item("hello") + "\n")
        tailer.poll()
        assert [write.event.kind for write in submitted] == ["meta", "turn"]
        (cursor,) = tailer._snapshot()
        assert isinstance(cursor.source, FileTailSource)
        assert cursor.source.path == str(rollout)  # tailed from the exact owned path

    async def test_non_owned_codex_binding_registers_no_cursor(self) -> None:
        # Regression (c): a codex wire id TM did not seed has no owned descriptor (bind_exchange left
        # it None). register_session_cursor registers NO cursor, it stays pending: no glob, no
        # error, no busy-poll (the old window-id phantom path is gone).
        submitted: list[EventWrite] = []
        tailer = _event_tailer(submitted)
        await register_session_cursor(
            tailer,
            CodexAdapter(),
            _codex_wire_binding("019e0000-0000-7000-8000-0000000000ff", None),
        )
        assert tailer._snapshot() == []  # nothing registered
        tailer.poll()  # nothing to poll
        assert submitted == []

    async def test_five_managed_sessions_same_cwd_no_cross_binding(self, tmp_path: Path) -> None:
        # Regression (b): 5 managed codex sessions in the SAME cwd, each a unique uuid + owned
        # rollout path, one response each. Assert zero cross-binding, every cursor tails ITS own
        # path and emits ITS own session's turn (no newest-glob: each path is owned, not discovered).
        natives = [f"019e0000-0000-7000-8000-0000000{i:05d}" for i in range(5)]
        paths: list[str] = []
        submitted: list[EventWrite] = []
        tailer = _event_tailer(submitted)
        for i, native in enumerate(natives):
            rollout = tmp_path / f"rollout-2026-06-05T10-00-0{i}-{native}.jsonl"
            rollout.write_text(
                _codex_session_meta(native) + "\n" + _codex_response_item(f"msg-{i}") + "\n",
                encoding="utf-8",
            )
            paths.append(str(rollout))
            descriptor = encode_source_descriptor(
                FileTailSource(path=str(rollout), format="codex_rollout")
            )
            await register_session_cursor(
                tailer, CodexAdapter(), _codex_wire_binding(native, descriptor)
            )

        cursors = tailer._snapshot()
        assert len(cursors) == 5  # five distinct cursors (distinct synth session_ids)
        # each cursor is bound to ITS OWN owned path, no two share, none point at "newest"
        source_paths = set()
        for c in cursors:
            assert isinstance(c.source, FileTailSource)
            source_paths.add(c.source.path)
        assert source_paths == set(paths)
        expected_ids = {synth_session_id(_RUN, "codex", n) for n in natives}
        assert {c.binding.session_id for c in cursors} == expected_ids

        tailer.poll()
        # one turn per session, and each turn's session_id is the one whose rollout it came from
        emitted = {write.event.session_id for write in submitted if write.event.kind == "turn"}
        assert len(submitted) == 10
        assert emitted == expected_ids  # zero cross-binding


class TestCodexModelThreading:
    def test_tail_threads_turn_context_model_onto_codex_turns(self) -> None:
        # codex carries its model in a separate `turn_context` record (which normalize skips), so the
        # tailer must thread it forward to every response_item event.
        from pathlib import Path as _Path

        from transport_matters.index.adapters.codex import CodexAdapter
        from transport_matters.index.sessions import synth_session_id

        fixture = (
            _Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "codex_rollout.jsonl"
        )
        native = "019e0000-0000-7000-8000-00000000c0de"
        binding = make_binding(
            synth_session_id("run1", "codex", native),
            provider="codex",
            cli="codex",
            native_session_id=native,
        )
        submitted: list[EventWrite] = []
        tailer = _event_tailer(submitted)
        tailer.register(
            TailCursor(
                binding=binding,
                source=FileTailSource(path=str(fixture), format="codex_rollout"),
                adapter=CodexAdapter(),
            )
        )
        tailer.poll()

        models = [write.event.model for write in submitted if write.event.kind == "turn"]
        assert models
        assert all(model == "gpt-5-codex" for model in models)
