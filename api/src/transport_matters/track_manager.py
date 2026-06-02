from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from transport_matters.storage.base import SpawnAnchor

if TYPE_CHECKING:
    from transport_matters.ir import (
        InternalRequest,
        InternalResponse,
        Message,
        ToolResultBlock,
    )

TrackRole = Literal["parent", "subagent"]
TrackStatus = Literal["open", "terminating", "closed"]


class AssignmentFields(TypedDict, total=False):
    track_id: str | None
    parent_track_id: str | None
    track_display_name: str | None
    track_role: TrackRole | None
    spawn_anchor: SpawnAnchor | None


@dataclass(frozen=True)
class TrackAssignment:
    track_id: str
    parent_track_id: str | None
    track_display_name: str | None
    track_role: TrackRole
    spawn_anchor: SpawnAnchor | None = None

    @property
    def track_spawn_exchange_id(self) -> str | None:
        return self.spawn_anchor.track_spawn_exchange_id if self.spawn_anchor is not None else None

    @property
    def track_spawn_tool_use_id(self) -> str | None:
        return self.spawn_anchor.track_spawn_tool_use_id if self.spawn_anchor is not None else None

    @property
    def track_spawn_order(self) -> int | None:
        return self.spawn_anchor.track_spawn_order if self.spawn_anchor else None


@dataclass(frozen=True)
class TrackSignature:
    tools_count: int
    cc_version_suffix: str | None = None


@dataclass
class TrackRecord:
    track_id: str
    parent_track_id: str | None
    display_name: str | None
    role: TrackRole
    status: TrackStatus = "open"
    signature: TrackSignature | None = None
    spawn_exchange_id: str | None = None
    spawn_tool_use_id: str | None = None
    spawn_order: int | None = None


@dataclass
class PendingSpawn:
    spawn_id: str
    provider: str
    parent_track_id: str
    display_name: str | None
    track_id: str | None = None
    spawn_exchange_id: str | None = None
    spawn_tool_use_id: str | None = None
    spawn_order: int | None = None


@dataclass
class RunTrackState:
    run_id: str
    tracks: dict[str, TrackRecord] = field(default_factory=dict)
    open_spawns: dict[str, PendingSpawn] = field(default_factory=dict)
    wait_targets: dict[str, list[str]] = field(default_factory=dict)
    track_tool_uses: dict[str, str] = field(default_factory=dict)


class TrackManager:
    """Classify ingest exchanges into parent and subagent tracks.

    The manager is intentionally process local and I/O free. Callers provide IR
    objects in ingest order for each run.
    """

    def __init__(self) -> None:
        self._runs: dict[str, RunTrackState] = {}

    def record_exchange(
        self,
        run_id: str,
        request: InternalRequest,
        response: InternalResponse | None,
        *,
        exchange_id: str | None = None,
    ) -> TrackAssignment:
        assignment = self.classify_request(run_id, request)
        if response is not None:
            self.observe_response(
                run_id,
                assignment.track_id,
                response,
                exchange_id=exchange_id,
            )
        return assignment

    def classify_request(
        self,
        run_id: str,
        request: InternalRequest,
    ) -> TrackAssignment:
        state = self._state(run_id)
        parent_track_id = self._resolve_tool_results(state, request)
        assignment = self._assign_request(state, request, parent_track_id)
        self._observe_request_signature(state, assignment.track_id, request)
        return self._assignment(state, assignment.track_id)

    def observe_response(
        self,
        run_id: str,
        current_track_id: str,
        response: InternalResponse,
        *,
        exchange_id: str | None = None,
    ) -> None:
        """Record response tool uses and capture subagent spawn anchors.

        ``spawn_order`` is scoped to this response. It disambiguates multiple
        child tracks that share one ``track_spawn_exchange_id``; chronology
        across responses comes from distinct spawn exchange anchors and parent
        exchange ordering.
        """
        state = self._state(run_id)
        # Response local ordinal for sibling spawns that share this exchange.
        spawn_order = 0
        for block in response.content:
            if block.type != "tool_use":
                continue
            state.track_tool_uses[block.id] = current_track_id
            if block.name == "Agent":
                self._register_anthropic_spawn(
                    state,
                    current_track_id,
                    block.id,
                    block.input,
                    spawn_exchange_id=exchange_id,
                    spawn_order=spawn_order,
                )
                spawn_order += 1
            elif block.name == "spawn_agent":
                self._register_codex_spawn(
                    state,
                    current_track_id,
                    block.id,
                    block.input,
                    spawn_exchange_id=exchange_id,
                    spawn_order=spawn_order,
                )
                spawn_order += 1
            elif block.name == "wait_agent":
                targets = _string_list(block.input.get("targets"))
                if targets:
                    state.wait_targets[block.id] = targets
                    for target in targets:
                        if target in state.tracks:
                            state.tracks[target].status = "terminating"
            elif block.name == "agent_kill":
                for target in _agent_kill_targets(block.input):
                    if target in state.tracks:
                        state.tracks[target].status = "closed"

    def tracks(self, run_id: str) -> dict[str, TrackRecord]:
        return dict(self._state(run_id).tracks)

    def _state(self, run_id: str) -> RunTrackState:
        state = self._runs.get(run_id)
        if state is None:
            state = RunTrackState(run_id=run_id)
            state.tracks[run_id] = TrackRecord(
                track_id=run_id,
                parent_track_id=None,
                display_name=None,
                role="parent",
            )
            self._runs[run_id] = state
        return state

    def _register_anthropic_spawn(
        self,
        state: RunTrackState,
        parent_track_id: str,
        spawn_id: str,
        input_payload: dict[str, Any],
        *,
        spawn_exchange_id: str | None = None,
        spawn_order: int | None = None,
    ) -> None:
        # The ordinal is scoped to the parent response, not the full track.
        display_name = _string_or_none(input_payload.get("subagent_type"))
        state.open_spawns[spawn_id] = PendingSpawn(
            spawn_id=spawn_id,
            provider="anthropic",
            parent_track_id=parent_track_id,
            display_name=display_name,
            track_id=spawn_id,
            spawn_exchange_id=spawn_exchange_id,
            spawn_tool_use_id=spawn_id,
            spawn_order=spawn_order,
        )
        state.tracks.setdefault(
            spawn_id,
            TrackRecord(
                track_id=spawn_id,
                parent_track_id=parent_track_id,
                display_name=display_name,
                role="subagent",
                spawn_exchange_id=spawn_exchange_id,
                spawn_tool_use_id=spawn_id,
                spawn_order=spawn_order,
            ),
        )

    def _register_codex_spawn(
        self,
        state: RunTrackState,
        parent_track_id: str,
        spawn_id: str,
        input_payload: dict[str, Any],
        *,
        spawn_exchange_id: str | None = None,
        spawn_order: int | None = None,
    ) -> None:
        # The ordinal is scoped to the parent response, not the full track.
        display_name = _string_or_none(input_payload.get("agent_type"))
        state.open_spawns[spawn_id] = PendingSpawn(
            spawn_id=spawn_id,
            provider="codex",
            parent_track_id=parent_track_id,
            display_name=display_name,
            spawn_exchange_id=spawn_exchange_id,
            spawn_tool_use_id=spawn_id,
            spawn_order=spawn_order,
        )

    def _resolve_tool_results(self, state: RunTrackState, request: InternalRequest) -> str | None:
        parent_track_ids: set[str] = set()
        owner_track_ids: set[str] = set()
        stale_owner_seen = False
        for result in _tool_results(request.messages):
            pending = state.open_spawns.get(result.tool_use_id)
            if pending is not None:
                parent_track_ids.add(pending.parent_track_id)
                self._resolve_spawn_tool_result(state, pending, result)
                continue

            wait_targets = state.wait_targets.pop(result.tool_use_id, None)
            if wait_targets is not None:
                for target in wait_targets:
                    track = state.tracks.get(target)
                    if track is not None and track.parent_track_id is not None:
                        parent_track_ids.add(track.parent_track_id)
                self._resolve_wait_result(state, wait_targets, result)
                continue

            owner_track_id = state.track_tool_uses.get(result.tool_use_id)
            if owner_track_id is not None:
                owner_track = state.tracks.get(owner_track_id)
                if owner_track is not None and owner_track.status != "closed":
                    owner_track_ids.add(owner_track_id)
                else:
                    stale_owner_seen = True
        if len(parent_track_ids) == 1:
            return parent_track_ids.pop()
        if parent_track_ids:
            return None
        if len(owner_track_ids) == 1:
            return owner_track_ids.pop()
        if stale_owner_seen:
            return state.run_id
        return None

    def _resolve_spawn_tool_result(
        self,
        state: RunTrackState,
        pending: PendingSpawn,
        result: ToolResultBlock,
    ) -> None:
        if pending.provider == "anthropic":
            track_id = pending.track_id or pending.spawn_id
            if track_id in state.tracks:
                state.tracks[track_id].status = "closed"
            state.open_spawns.pop(pending.spawn_id, None)
            return

        payload = _json_payload(result)
        agent_id = _string_or_none(payload.get("agent_id")) if payload is not None else None
        if agent_id is None:
            state.open_spawns.pop(pending.spawn_id, None)
            return

        assert payload is not None
        display_name = (
            _string_or_none(payload.get("nickname"))
            or pending.display_name
            or _string_or_none(payload.get("agent_id"))
        )
        pending.track_id = agent_id
        pending.display_name = display_name
        state.tracks[agent_id] = TrackRecord(
            track_id=agent_id,
            parent_track_id=pending.parent_track_id,
            display_name=display_name,
            role="subagent",
            spawn_exchange_id=pending.spawn_exchange_id,
            spawn_tool_use_id=pending.spawn_tool_use_id,
            spawn_order=pending.spawn_order,
        )
        state.open_spawns.pop(pending.spawn_id, None)

    def _resolve_wait_result(
        self,
        state: RunTrackState,
        wait_targets: list[str],
        result: ToolResultBlock,
    ) -> None:
        payload = _json_payload(result)
        if payload is None:
            return
        if payload.get("timed_out") is True:
            return
        statuses = payload.get("status")
        if not isinstance(statuses, dict):
            return
        for target in wait_targets:
            if target in statuses and target in state.tracks:
                state.tracks[target].status = "closed"

    def _assign_request(
        self,
        state: RunTrackState,
        request: InternalRequest,
        parent_track_id: str | None = None,
    ) -> TrackAssignment:
        if parent_track_id is not None:
            return self._assignment(state, parent_track_id)

        parent_track_id = self._parent_track_for_tool_result(state, request)
        if parent_track_id is not None:
            return self._assignment(state, parent_track_id)

        codex_track_id = _codex_subagent_track_id(request)
        if codex_track_id is not None:
            if codex_track_id not in state.tracks:
                state.tracks[codex_track_id] = TrackRecord(
                    track_id=codex_track_id,
                    parent_track_id=state.run_id,
                    display_name=None,
                    role="subagent",
                )
            return self._assignment(state, codex_track_id)

        unassigned = [
            track.track_id
            for track in state.tracks.values()
            if track.role == "subagent" and track.status != "closed" and track.signature is None
        ]
        if unassigned:
            return self._assignment(state, unassigned[0])

        signature = _request_signature(request)
        signature_matches = [
            track.track_id
            for track in state.tracks.values()
            if track.role == "subagent"
            and track.status != "closed"
            and track.signature == signature
        ]
        if len(signature_matches) == 1:
            return self._assignment(state, signature_matches[0])

        return self._assignment(state, state.run_id)

    def _parent_track_for_tool_result(
        self, state: RunTrackState, request: InternalRequest
    ) -> str | None:
        for result in _tool_results(request.messages):
            pending = state.open_spawns.get(result.tool_use_id)
            if pending is not None:
                return pending.parent_track_id
            targets = state.wait_targets.get(result.tool_use_id)
            if targets:
                parents = {
                    state.tracks[target].parent_track_id
                    for target in targets
                    if target in state.tracks and state.tracks[target].parent_track_id is not None
                }
                if len(parents) == 1:
                    return parents.pop()
        return None

    def _observe_request_signature(
        self, state: RunTrackState, track_id: str, request: InternalRequest
    ) -> None:
        track = state.tracks[track_id]
        signature = _request_signature(request)
        if track.signature is None:
            track.signature = signature
        if track_id == state.run_id:
            return
        if track.display_name is None:
            codex_name = _codex_display_name_for_track(request, track_id)
            if codex_name is not None:
                track.display_name = codex_name

    def _assignment(self, state: RunTrackState, track_id: str) -> TrackAssignment:
        track = state.tracks[track_id]
        return TrackAssignment(
            track_id=track.track_id,
            parent_track_id=track.parent_track_id,
            track_display_name=track.display_name,
            track_role=track.role,
            spawn_anchor=(
                SpawnAnchor(
                    track_spawn_exchange_id=track.spawn_exchange_id,
                    track_spawn_tool_use_id=track.spawn_tool_use_id,
                    track_spawn_order=track.spawn_order,
                )
                if track.spawn_exchange_id is not None
                or track.spawn_tool_use_id is not None
                or track.spawn_order is not None
                else None
            ),
        )


_track_manager = TrackManager()


def get_track_manager() -> TrackManager:
    return _track_manager


def assignment_index_fields(
    assignment: TrackAssignment | None,
) -> AssignmentFields:
    if assignment is None:
        return {}
    return {
        "track_id": assignment.track_id,
        "parent_track_id": assignment.parent_track_id,
        "track_display_name": assignment.track_display_name,
        "track_role": assignment.track_role,
        "spawn_anchor": assignment.spawn_anchor,
    }


def _tool_results(messages: list[Message]) -> list[ToolResultBlock]:
    results: list[ToolResultBlock] = []
    for message in messages:
        for block in message.content:
            if block.type == "tool_result":
                results.append(block)
    return results


def _json_payload(result: ToolResultBlock) -> dict[str, Any] | None:
    text = "".join(block.text for block in result.content if block.type == "text")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _request_signature(request: InternalRequest) -> TrackSignature:
    return TrackSignature(
        tools_count=len(request.tools),
        cc_version_suffix=_cc_version_suffix(request),
    )


def _cc_version_suffix(request: InternalRequest) -> str | None:
    metadata = request.metadata.provider_metadata
    value = metadata.get("cc_version") or metadata.get("x-claude-code-version")
    if not isinstance(value, str):
        return None
    return value.rsplit(".", maxsplit=1)[-1]


def _codex_subagent_track_id(request: InternalRequest) -> str | None:
    if request.provider != "codex":
        return None
    metadata = request.metadata.provider_metadata
    if "x-openai-subagent" not in metadata and "x-codex-parent-thread-id" not in metadata:
        return None
    window_id = _string_or_none(metadata.get("x-codex-window-id"))
    if window_id:
        return window_id.split(":", maxsplit=1)[0]
    turn_metadata = _string_or_none(metadata.get("x-codex-turn-metadata"))
    if turn_metadata is None:
        return None
    try:
        payload = json.loads(turn_metadata)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return _string_or_none(payload.get("session_id"))


def _codex_display_name_for_track(request: InternalRequest, track_id: str) -> str | None:
    metadata = request.metadata.provider_metadata
    window_id = _string_or_none(metadata.get("x-codex-window-id"))
    if window_id and window_id.split(":", maxsplit=1)[0] == track_id:
        return _string_or_none(
            metadata.get("x-codex-subagent-nickname")
        ) or _codex_display_name_from_turn_metadata(metadata)
    if window_id is None:
        return _codex_display_name_from_turn_metadata(metadata)
    return None


def _codex_display_name_from_turn_metadata(metadata: dict[str, object]) -> str | None:
    turn_metadata = _string_or_none(metadata.get("x-codex-turn-metadata"))
    if turn_metadata is None:
        return None
    try:
        payload = json.loads(turn_metadata)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return (
        _string_or_none(payload.get("subagent_nickname"))
        or _string_or_none(payload.get("nickname"))
        or _string_or_none(payload.get("name"))
    )


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _agent_kill_targets(input_payload: dict[str, Any]) -> list[str]:
    targets = _string_list(input_payload.get("targets"))
    if targets:
        return targets
    target = _string_or_none(input_payload.get("target"))
    return [target] if target is not None else []
