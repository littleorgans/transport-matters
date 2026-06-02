"""Helpers for restoring opaque provider data onto wire dictionaries."""

from typing import Any, Protocol


class ProviderDataCarrier(Protocol):
    @property
    def provider_data(self) -> dict[str, Any] | None: ...


def restore_provider_data(
    target: dict[str, Any],
    obj: ProviderDataCarrier,
) -> None:
    if obj.provider_data:
        target.update(obj.provider_data)
