"""Structural diff decisions for the request pipeline.

Single source of truth for whether the pipeline left an outbound request
identical to the captured original. Consumed by the live proxy handlers,
breakpoint release, exchange persistence, and token counting so they all
agree on one structural-equality contract.
"""

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from transport_matters.ir import InternalRequest


def request_unchanged(original_ir: InternalRequest, curated_ir: InternalRequest) -> bool:
    """True when the curated request is structurally identical to the original.

    IR models are ``frozen``, so equality is a deep value comparison. When this
    holds, the original captured wire bytes can be forwarded as-is: no IR
    reserialization, no curated-raw artifact, and no redundant after-count.
    """
    return curated_ir == original_ir


def outbound_request_if_changed(
    adapter: Any,  # Any: adapter protocol has no shared base
    original_ir: InternalRequest,
    curated_ir: InternalRequest,
) -> bytes | None:
    """Serialized outbound bytes when the pipeline changed the request, else None.

    ``None`` is the instruction to forward the original captured wire bytes
    untouched. The adapter is only invoked when a change is present, so an
    unchanged request never pays for reserialization.
    """
    if request_unchanged(original_ir, curated_ir):
        return None
    return cast("bytes", adapter.outbound_request(curated_ir))
