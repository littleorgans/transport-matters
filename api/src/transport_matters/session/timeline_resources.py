from __future__ import annotations

from typing import TYPE_CHECKING

from transport_matters.session import exchange_correlation
from transport_matters.session.resource_ids import (
    inline_resource_id,
    native_resource_id,
    wire_resource_id,
)
from transport_matters.session.timeline_models import (
    ContentPart,
    ContextItem,
    InlineResourceSummary,
    NativeRecordResourceSummary,
    ResourceConfidence,
    ResourceRef,
    ResourceRelation,
    ResourceSummaryType,
    SourceRef,
    WireResourceSummary,
)

if TYPE_CHECKING:
    from transport_matters.session.models import EventArtifactRow, EventRow

_INLINE_ARTIFACT_TITLE = "Inline artifact"
_NATIVE_RECORD_TITLE = "Native record"
_WIRE_EXCHANGE_TITLE = "Wire exchange"


def message_resources(
    row: EventRow, parts: list[ContentPart], *, source: SourceRef
) -> tuple[list[ResourceRef], dict[str, ResourceSummaryType]]:
    refs: list[ResourceRef] = []
    resources: dict[str, ResourceSummaryType] = {}
    seen_refs: set[tuple[str, int | None]] = set()

    _add_native_record_resource(
        row, source=source, refs=refs, resources=resources, seen_refs=seen_refs
    )
    _add_inline_artifact_resources(
        row,
        parts,
        refs=refs,
        resources=resources,
        seen_refs=seen_refs,
    )
    _add_wire_resource(row, refs=refs, resources=resources, seen_refs=seen_refs)
    return refs, resources


def context_item_with_resources(
    row: EventRow, item: ContextItem
) -> tuple[ContextItem, dict[str, ResourceSummaryType]]:
    refs: list[ResourceRef] = []
    resources: dict[str, ResourceSummaryType] = {}
    seen_refs: set[tuple[str, int | None]] = set()
    _add_native_record_resource(
        row,
        source=item.source,
        refs=refs,
        resources=resources,
        seen_refs=seen_refs,
    )
    _add_wire_resource(row, refs=refs, resources=resources, seen_refs=seen_refs)
    return item.model_copy(update={"resource_refs": refs}), resources


def _add_native_record_resource(
    row: EventRow,
    *,
    source: SourceRef,
    refs: list[ResourceRef],
    resources: dict[str, ResourceSummaryType],
    seen_refs: set[tuple[str, int | None]],
) -> None:
    resource_id = native_resource_id(row.session_id, row.seq)
    _append_resource_ref(
        refs,
        seen_refs=seen_refs,
        resource_id=resource_id,
        relation="native-record",
        confidence="verified",
        block_index=None,
    )
    resources[resource_id] = NativeRecordResourceSummary(
        id=resource_id,
        title=_NATIVE_RECORD_TITLE,
        source=source,
    )


def _add_inline_artifact_resources(
    row: EventRow,
    parts: list[ContentPart],
    *,
    refs: list[ResourceRef],
    resources: dict[str, ResourceSummaryType],
    seen_refs: set[tuple[str, int | None]],
) -> None:
    artifact_by_hash = {artifact.artifact_hash: artifact for artifact in row.artifacts}
    emitted_artifacts: set[str] = set()

    for block_index, part in enumerate(parts):
        artifact_hash = _inline_artifact_hash(part)
        if artifact_hash is None or artifact_hash in emitted_artifacts:
            continue
        artifact = artifact_by_hash.get(artifact_hash)
        _add_inline_artifact_resource(
            artifact_hash=artifact_hash,
            media_type=_inline_media_type(part, artifact),
            size_bytes=_inline_size_bytes(part, artifact),
            block_index=block_index,
            refs=refs,
            resources=resources,
            seen_refs=seen_refs,
        )
        emitted_artifacts.add(artifact_hash)

    for artifact in row.artifacts:
        artifact_block_index = _artifact_block_index(artifact)
        if artifact.artifact_hash in emitted_artifacts:
            continue
        _add_inline_artifact_resource(
            artifact_hash=artifact.artifact_hash,
            media_type=artifact.media_type or "application/octet-stream",
            size_bytes=artifact.size_bytes or 0,
            block_index=artifact_block_index,
            refs=refs,
            resources=resources,
            seen_refs=seen_refs,
        )
        emitted_artifacts.add(artifact.artifact_hash)


def _add_inline_artifact_resource(
    *,
    artifact_hash: str,
    media_type: str,
    size_bytes: int,
    block_index: int | None,
    refs: list[ResourceRef],
    resources: dict[str, ResourceSummaryType],
    seen_refs: set[tuple[str, int | None]],
) -> None:
    resource_id = inline_resource_id(artifact_hash)
    _append_resource_ref(
        refs,
        seen_refs=seen_refs,
        resource_id=resource_id,
        relation="attached",
        confidence="verified",
        block_index=block_index,
    )
    resources[resource_id] = InlineResourceSummary(
        id=resource_id,
        title=_INLINE_ARTIFACT_TITLE,
        media_type=media_type,
        artifact_hash=artifact_hash,
        size_bytes=size_bytes,
    )


def _add_wire_resource(
    row: EventRow,
    *,
    refs: list[ResourceRef],
    resources: dict[str, ResourceSummaryType],
    seen_refs: set[tuple[str, int | None]],
) -> None:
    exchange_id = _wire_exchange_id(row)
    if exchange_id is None:
        return
    resource_id = wire_resource_id(exchange_id)
    _append_resource_ref(
        refs,
        seen_refs=seen_refs,
        resource_id=resource_id,
        relation="wire-evidence",
        confidence="verified",
        block_index=None,
    )
    resources[resource_id] = WireResourceSummary(
        id=resource_id,
        title=_WIRE_EXCHANGE_TITLE,
        exchange_id=exchange_id,
        structured_only=True,
    )


def _append_resource_ref(
    refs: list[ResourceRef],
    *,
    seen_refs: set[tuple[str, int | None]],
    resource_id: str,
    relation: ResourceRelation,
    confidence: ResourceConfidence,
    block_index: int | None,
) -> None:
    key = (resource_id, block_index)
    if key in seen_refs:
        return
    refs.append(
        ResourceRef(
            resource_id=resource_id,
            relation=relation,
            confidence=confidence,
            block_index=block_index,
        )
    )
    seen_refs.add(key)


def _inline_artifact_hash(part: ContentPart) -> str | None:
    if part.get("type") != "image":
        return None
    return _non_empty_string(part.get("artifact_hash")) or _non_empty_string(
        part.get("artifactHash")
    )


def _inline_media_type(part: ContentPart, artifact: EventArtifactRow | None) -> str:
    artifact_media_type = None if artifact is None else artifact.media_type
    return (
        _non_empty_string(artifact_media_type)
        or _non_empty_string(part.get("media_type"))
        or _non_empty_string(part.get("mediaType"))
        or "application/octet-stream"
    )


def _inline_size_bytes(part: ContentPart, artifact: EventArtifactRow | None) -> int:
    artifact_size_bytes = None if artifact is None else artifact.size_bytes
    if isinstance(artifact_size_bytes, int) and not isinstance(artifact_size_bytes, bool):
        return artifact_size_bytes
    for key in ("size_bytes", "sizeBytes"):
        value = part.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return 0


def _artifact_block_index(artifact: EventArtifactRow) -> int | None:
    ref = artifact.ref
    if not isinstance(ref, dict):
        return None
    block_index = ref.get("block_index")
    if isinstance(block_index, int) and not isinstance(block_index, bool) and block_index >= 0:
        return block_index
    return None


def _wire_exchange_id(row: EventRow) -> str | None:
    return exchange_correlation.exchange_id_from_record(row.ir)


def _non_empty_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
