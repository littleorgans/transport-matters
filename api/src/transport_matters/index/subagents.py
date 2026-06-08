from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from transport_matters.index.adapters.base import (
    FileTailSource,
    RawRecord,
    SessionBinding,
    encode_source_descriptor,
)
from transport_matters.index.sessions import synth_session_id

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator


@dataclass(frozen=True)
class SubagentSpawnLink:
    parent_seq: int
    title: str | None = None
    replay_anchor_text: str | None = None


@dataclass(frozen=True)
class ChildTranscript:
    binding: SessionBinding
    source: FileTailSource
    skip_until_user_text: str | None = None


def record_subagent_spawn_links(
    *,
    provider: str,
    records: Iterable[RawRecord],
    start_seq: int,
    links: dict[str, SubagentSpawnLink],
    pending_codex_calls: dict[str, SubagentSpawnLink],
) -> None:
    for offset, record in enumerate(records):
        seq = start_seq + offset
        if provider == "anthropic":
            _record_claude_spawn_links(record, seq, links)
        elif provider == "codex":
            _record_codex_spawn_links(record, seq, links, pending_codex_calls)


def discover_child_transcripts(
    *,
    parent_binding: SessionBinding,
    parent_source: FileTailSource,
    spawn_links: dict[str, SubagentSpawnLink],
) -> list[ChildTranscript]:
    if parent_binding.parent_session_id is not None:
        return []
    if parent_binding.provider == "anthropic":
        return _discover_claude_children(parent_binding, parent_source, spawn_links)
    if parent_binding.provider == "codex":
        return _discover_codex_children(parent_binding, parent_source, spawn_links)
    return []


def iter_without_replayed_prefix(
    records: Iterable[RawRecord], skip_until_user_text: str | None
) -> Iterator[RawRecord]:
    if skip_until_user_text is None:
        yield from records
        return
    found = False
    for record in records:
        if not found:
            found = _is_user_text_record(record, skip_until_user_text)
            if not found:
                continue
        yield record


def is_replay_anchor(record: RawRecord, text: str) -> bool:
    return _is_user_text_record(record, text)


def _record_claude_spawn_links(
    record: RawRecord, seq: int, links: dict[str, SubagentSpawnLink]
) -> None:
    if record.get("type") != "assistant":
        return
    message = record.get("message")
    if not isinstance(message, dict):
        return
    for block in _content_blocks(message.get("content")):
        if block.get("type") != "tool_use":
            continue
        name = block.get("name")
        if name not in {"Agent", "Task"}:
            continue
        tool_id = block.get("id")
        if not isinstance(tool_id, str) or not tool_id:
            continue
        raw_input = block.get("input")
        input_ = raw_input if isinstance(raw_input, dict) else {}
        description = _string(input_.get("description")) or _string(input_.get("subagent_type"))
        links.setdefault(tool_id, SubagentSpawnLink(parent_seq=seq, title=description))


def _record_codex_spawn_links(
    record: RawRecord,
    seq: int,
    links: dict[str, SubagentSpawnLink],
    pending_calls: dict[str, SubagentSpawnLink],
) -> None:
    if record.get("type") != "response_item":
        return
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return
    kind = payload.get("type")
    call_id = _string(payload.get("call_id"))
    if kind == "function_call" and payload.get("name") == "spawn_agent" and call_id:
        arguments = _json_object(payload.get("arguments"))
        message = _string(arguments.get("message"))
        pending_calls[call_id] = SubagentSpawnLink(
            parent_seq=seq,
            title=message,
            replay_anchor_text=message,
        )
        return
    if kind != "function_call_output" or not call_id:
        return
    pending = pending_calls.pop(call_id, None)
    if pending is None:
        return
    output = _json_object(payload.get("output"))
    agent_id = _string(output.get("agent_id"))
    if agent_id:
        links.setdefault(agent_id, pending)


def _discover_claude_children(
    parent: SessionBinding,
    source: FileTailSource,
    links: dict[str, SubagentSpawnLink],
) -> list[ChildTranscript]:
    parent_path = Path(source.path)
    subagents_dir = parent_path.with_suffix("") / "subagents"
    if not subagents_dir.is_dir():
        return []
    children: list[ChildTranscript] = []
    for transcript in sorted(subagents_dir.glob("agent-*.jsonl")):
        agent_id = transcript.stem.removeprefix("agent-")
        meta = _read_json_object(transcript.with_suffix(".meta.json"))
        tool_use_id = _string(meta.get("toolUseId"))
        link = links.get(tool_use_id or "")
        if link is None:
            continue
        child_source = _child_source(source, transcript)
        title = _string(meta.get("description")) or _string(meta.get("agentType")) or link.title
        child_id = synth_session_id(
            parent.run_id,
            parent.provider,
            f"{parent.session_id}:claude-subagent:{agent_id}",
        )
        children.append(
            ChildTranscript(
                binding=parent.model_copy(
                    update={
                        "session_id": child_id,
                        "native_session_id": agent_id,
                        "minted": False,
                        "source_descriptor": encode_source_descriptor(child_source),
                        "parent_session_id": parent.session_id,
                        "forked_at_seq": link.parent_seq,
                        "title": title or agent_id,
                        "started_at": _first_timestamp(transcript) or parent.started_at,
                    }
                ),
                source=child_source,
            )
        )
    return children


def _discover_codex_children(
    parent: SessionBinding,
    source: FileTailSource,
    links: dict[str, SubagentSpawnLink],
) -> list[ChildTranscript]:
    parent_thread_id = parent.native_session_id
    if parent_thread_id is None:
        return []
    parent_path = Path(source.path)
    children: list[ChildTranscript] = []
    for transcript in sorted(parent_path.parent.glob("rollout-*.jsonl")):
        if transcript == parent_path:
            continue
        meta = _first_session_meta(transcript)
        if not _is_codex_child_meta(meta, parent_thread_id):
            continue
        child_thread_id = _string(meta.get("id"))
        if child_thread_id is None or child_thread_id == parent_thread_id:
            continue
        link = links.get(child_thread_id)
        if link is None:
            continue
        child_source = _child_source(source, transcript)
        title = _string(meta.get("agent_nickname")) or link.title or child_thread_id
        children.append(
            ChildTranscript(
                binding=parent.model_copy(
                    update={
                        "session_id": synth_session_id(
                            parent.run_id, parent.provider, child_thread_id
                        ),
                        "native_session_id": child_thread_id,
                        "minted": False,
                        "source_descriptor": encode_source_descriptor(child_source),
                        "parent_session_id": parent.session_id,
                        "forked_at_seq": link.parent_seq,
                        "title": title,
                        "started_at": _string(meta.get("timestamp")) or parent.started_at,
                    }
                ),
                source=child_source,
                skip_until_user_text=link.replay_anchor_text,
            )
        )
    return children


def _is_codex_child_meta(meta: dict[str, Any], parent_thread_id: str) -> bool:
    parent_id = _string(meta.get("parent_thread_id")) or _string(meta.get("forked_from_id"))
    source = meta.get("source")
    if parent_id is None and isinstance(source, dict):
        spawn = source.get("subagent", {}).get("thread_spawn", {})
        if isinstance(spawn, dict):
            parent_id = _string(spawn.get("parent_thread_id"))
    return parent_id == parent_thread_id


def _child_source(parent: FileTailSource, path: Path) -> FileTailSource:
    return FileTailSource(
        path=str(path),
        format=parent.format,
        encoding=parent.encoding,
        home_dir=parent.home_dir,
    )


def _content_blocks(content: Any) -> Iterator[dict[str, Any]]:
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                yield item


def _is_user_text_record(record: RawRecord, text: str) -> bool:
    if record.get("type") != "response_item":
        return False
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return False
    if payload.get("type") != "message" or payload.get("role") != "user":
        return False
    for block in _content_blocks(payload.get("content")):
        if block.get("type") == "input_text" and block.get("text") == text:
            return True
    return False


def _first_session_meta(path: Path) -> dict[str, Any]:
    for record in _jsonl_records(path):
        if record.get("type") == "session_meta":
            payload = record.get("payload")
            return payload if isinstance(payload, dict) else {}
    return {}


def _first_timestamp(path: Path) -> str | None:
    for record in _jsonl_records(path):
        return _string(record.get("timestamp"))
    return None


def _jsonl_records(path: Path) -> Iterator[RawRecord]:
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    yield record
    except FileNotFoundError:
        return


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError, json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
