"""Provider model ID prefix helpers."""

from __future__ import annotations


def normalise_model(model: str, prefix: str) -> str:
    if model.startswith(prefix):
        return model
    return f"{prefix}{model}"


def denormalise_model(model: str, prefix: str) -> str:
    if model.startswith(prefix):
        return model[len(prefix) :]
    return model
