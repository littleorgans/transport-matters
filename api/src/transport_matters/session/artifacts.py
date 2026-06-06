from __future__ import annotations

import base64
from hashlib import blake2b
from typing import TYPE_CHECKING, Any

from pydantic import TypeAdapter

from transport_matters.ir import ContentBlock, ImageBlock
from transport_matters.session.models import InlineArtifact

ARTIFACT_HASH_ALGO = "blake2b-256"
_CONTENT_BLOCKS = TypeAdapter(list[ContentBlock])

if TYPE_CHECKING:
    from collections.abc import Iterable


def artifact_hash(data: bytes) -> str:
    return blake2b(data, digest_size=32).hexdigest()


def inline_artifacts_from_ir(ir: dict[str, Any] | None) -> list[InlineArtifact]:
    # Any: ir is provider normalized JSON loaded from event.ir.
    if ir is None:
        return []
    raw_parts = ir.get("parts")
    if not isinstance(raw_parts, list):
        return []
    parts = _CONTENT_BLOCKS.validate_python(raw_parts)
    return list(inline_artifacts_from_parts(parts))


def inline_artifacts_from_parts(parts: Iterable[ContentBlock]) -> list[InlineArtifact]:
    artifacts: list[InlineArtifact] = []
    for pos, part in enumerate(parts):
        if isinstance(part, ImageBlock):
            artifact = inline_artifact_from_image(part, pos)
            if artifact is not None:
                artifacts.append(artifact)
    return artifacts


def inline_artifact_from_image(block: ImageBlock, pos: int) -> InlineArtifact | None:
    source = block.source
    media_type, data = _decode_base64_source(source)
    if data is None:
        return None
    return InlineArtifact(
        media_type=media_type,
        data=data,
        ref={"block_index": pos, "source": _source_ref(source)},
    )


def _decode_base64_source(source: dict[str, Any]) -> tuple[str | None, bytes | None]:
    # Any: source is provider image JSON preserved by the IR boundary.
    if isinstance(source.get("data"), str):
        media_type = source.get("media_type") if isinstance(source.get("media_type"), str) else None
        return media_type, _b64decode(source["data"])
    image_url = source.get("image_url")
    if isinstance(image_url, str) and image_url.startswith("data:"):
        return _decode_data_url(image_url)
    return None, None


def _decode_data_url(value: str) -> tuple[str | None, bytes | None]:
    header, separator, payload = value.partition(",")
    if separator != "," or ";base64" not in header:
        return None, None
    media_type = header.removeprefix("data:").split(";", 1)[0] or None
    return media_type, _b64decode(payload)


def _b64decode(value: str) -> bytes | None:
    try:
        return base64.b64decode(value, validate=True)
    except ValueError:
        return None


def _source_ref(source: dict[str, Any]) -> dict[str, str]:
    # Any: source is provider image JSON preserved by the IR boundary.
    if "image_url" in source:
        return {"field": "source.image_url"}
    if "data" in source:
        return {"field": "source.data"}
    return {"field": "source"}
