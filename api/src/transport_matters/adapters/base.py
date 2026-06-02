"""Abstract base class for provider adapters.

Each adapter translates between a specific provider's wire format
and the canonical IR models.  Adapters are registered in ``__init__.py``
and selected at runtime via ``matches(flow)``.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any  # Any: flow is untyped mitmproxy object

if TYPE_CHECKING:
    from transport_matters.ir import InternalRequest, InternalResponse


class ProviderAdapter(ABC):
    """Translate between a provider wire format and the internal IR."""

    name: str

    @abstractmethod
    def matches(self, flow: Any) -> bool:  # Any: mitmproxy flow object, untyped
        """Return True if this adapter should handle the given flow."""
        ...

    @abstractmethod
    def inbound_request(self, raw_body: bytes) -> InternalRequest:
        """Parse a raw provider request body into an InternalRequest."""
        ...

    @abstractmethod
    def outbound_request(self, ir: InternalRequest) -> bytes:
        """Serialize an InternalRequest back to provider wire bytes."""
        ...

    @abstractmethod
    def inbound_response(self, raw_body: bytes, content_type: str) -> InternalResponse:
        """Parse a raw provider response body into an InternalResponse."""
        ...
