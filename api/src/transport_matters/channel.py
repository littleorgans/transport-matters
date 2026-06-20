"""Channel resolution for side-by-side Transport Matters instances."""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal, cast

from transport_matters import env_keys

_CHANNEL_SPECS_FILENAME = "channel-specs.json"
_DEFAULT_CHANNEL_ID = "stable"
_CHANNEL_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class ChannelBadge:
    text: str
    color: Literal["amber"]
    hex: str


@dataclass(frozen=True, slots=True)
class ChannelSpec:
    id: str
    label: str
    home: Path
    database_name: str
    proxy_port: int
    web_port: int
    electron_app_name: str
    electron_app_id: str
    electron_user_data: Path | None
    dock_icon: Literal["default", "preview-amber"]
    badge: ChannelBadge | None


def resolve_channel_id(value: str | None, env: Mapping[str, str]) -> str:
    """Return the canonical channel id after validating format and existence."""
    raw = value if value is not None else env.get(env_keys.CHANNEL, _DEFAULT_CHANNEL_ID)
    if not _CHANNEL_ID_RE.fullmatch(raw):
        raise ValueError(f"invalid channel id {raw!r}; expected {_CHANNEL_ID_RE.pattern}")
    if raw not in _channel_specs_by_id():
        known = ", ".join(spec.id for spec in all_channel_specs())
        raise ValueError(f"unknown channel {raw!r}; expected one of: {known}")
    return raw


def resolve_channel_spec(
    value: str | None = None, env: Mapping[str, str] = os.environ
) -> ChannelSpec:
    """Resolve a channel id to its package-owned channel spec."""
    return _channel_specs_by_id()[resolve_channel_id(value, env)]


def activate_channel(value: str | None) -> ChannelSpec:
    """Set the process channel env and clear cached settings if they exist."""
    spec = resolve_channel_spec(value)
    os.environ[env_keys.CHANNEL] = spec.id
    config_module = sys.modules.get("transport_matters.config")
    get_settings = getattr(config_module, "get_settings", None)
    if get_settings is not None:
        get_settings.cache_clear()
    return spec


def all_channel_specs() -> tuple[ChannelSpec, ...]:
    """Return channel specs in committed JSON order."""
    return _channel_specs()


@lru_cache(maxsize=1)
def _channel_specs() -> tuple[ChannelSpec, ...]:
    raw = json.loads(
        (files("transport_matters") / _CHANNEL_SPECS_FILENAME).read_text(encoding="utf-8")
    )
    if not isinstance(raw, Mapping) or raw.get("schema") != 1:
        raise ValueError("channel-specs.json must use schema 1")
    channels = raw.get("channels")
    if not isinstance(channels, list):
        raise ValueError("channel-specs.json must contain a channels list")
    specs = tuple(_build_channel_spec(item) for item in channels)
    ids = [spec.id for spec in specs]
    if len(set(ids)) != len(ids):
        raise ValueError("channel-specs.json contains duplicate channel ids")
    return specs


@lru_cache(maxsize=1)
def _channel_specs_by_id() -> dict[str, ChannelSpec]:
    return {spec.id: spec for spec in _channel_specs()}


def _build_channel_spec(item: object) -> ChannelSpec:
    if not isinstance(item, Mapping):
        raise ValueError("channel entries must be objects")
    channel_id = _require_str(item, "id")
    if not _CHANNEL_ID_RE.fullmatch(channel_id):
        raise ValueError(f"invalid channel id {channel_id!r}")
    home = Path.home() / _require_str(item, "homeDir")
    electron = _require_mapping(item, "electron")
    user_data_dir = _optional_str(electron, "userDataDir")
    dock_icon_raw = _require_str(electron, "dockIcon")
    if dock_icon_raw not in ("default", "preview-amber"):
        raise ValueError(f"unsupported dock icon {dock_icon_raw!r}")
    dock_icon = cast("Literal['default', 'preview-amber']", dock_icon_raw)
    return ChannelSpec(
        id=channel_id,
        label=_require_str(item, "label"),
        home=home,
        database_name=_require_str(item, "databaseName"),
        proxy_port=_require_port(item, "proxyPort"),
        web_port=_require_port(item, "webPort"),
        electron_app_name=_require_str(electron, "appName"),
        electron_app_id=_require_str(electron, "appId"),
        electron_user_data=home / user_data_dir if user_data_dir is not None else None,
        dock_icon=dock_icon,
        badge=_build_badge(item.get("badge")),
    )


def _build_badge(value: object) -> ChannelBadge | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("channel badge must be null or an object")
    color = _require_str(value, "color")
    if color != "amber":
        raise ValueError(f"unsupported badge color {color!r}")
    return ChannelBadge(
        text=_require_str(value, "text"),
        color="amber",
        hex=_require_str(value, "hex"),
    )


def _require_mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"channel spec field {key!r} must be an object")
    return value


def _require_str(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"channel spec field {key!r} must be a non-empty string")
    return value


def _optional_str(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"channel spec field {key!r} must be null or a string")
    return value


def _require_port(data: Mapping[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 65536:
        raise ValueError(f"channel spec field {key!r} must be a TCP port")
    return value
