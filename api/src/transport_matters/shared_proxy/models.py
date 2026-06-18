"""Typed JSON models for the shared proxy control channel."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from transport_matters.overrides import Override
from transport_matters.shared_proxy.binding import ProxyRunBinding, require_run_id

# Any: launch fields are persisted dynamic harness metadata with provider-specific keys.
type LaunchFields = dict[str, Any]

ProxyModeKind = Literal["reverse", "regular"]


class SharedProxyBindingPayload(BaseModel):
    """Serializable subset of ProxyRunBinding sent to the shared subprocess."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    run_id: str = Field(alias="runId")
    harness: str | None = None
    working_dir: str | None = Field(default=None, alias="workingDir")
    storage_root: str | None = Field(default=None, alias="storageRoot")
    listen_port: int = Field(alias="listenPort", ge=1, le=65535)
    upstream: str | None = None
    agent_home_dir: str | None = Field(default=None, alias="agentHomeDir")
    owned_native_session_id: str | None = Field(default=None, alias="ownedNativeSessionId")
    owned_source_descriptor: str | None = Field(default=None, alias="ownedSourceDescriptor")
    launch_fields: LaunchFields = Field(default_factory=dict, alias="launchFields")
    default_client_passthrough: tuple[str, ...] = Field(
        default_factory=tuple,
        alias="defaultClientPassthrough",
    )
    breakpoint_skip_models: tuple[str, ...] = Field(
        default_factory=tuple,
        alias="breakpointSkipModels",
    )
    mode_kind: ProxyModeKind = Field(alias="modeKind")

    def mode_spec(self) -> str:
        """Return the mitmproxy mode spec for this listener."""

        if self.mode_kind == "regular":
            return f"regular@127.0.0.1:{self.listen_port}"
        if self.upstream is None:
            msg = "reverse shared proxy bindings require an upstream"
            raise ValueError(msg)
        return f"reverse:{self.upstream}@127.0.0.1:{self.listen_port}"


class OverrideScopePayload(BaseModel):
    """Run and optional track scope for override propagation."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    run_id: str | None = Field(default=None, alias="runId")
    track_id: str | None = Field(default=None, alias="trackId")


class OverrideSnapshotPayload(BaseModel):
    """Complete override state for one scope."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    overrides: tuple[Override, ...] = ()


class PingRequest(BaseModel):
    """Control channel readiness probe."""

    model_config = ConfigDict(frozen=True)

    type: Literal["ping"] = "ping"


class RegisterListenerRequest(BaseModel):
    """Add or replace one listener mode in the shared subprocess."""

    model_config = ConfigDict(frozen=True)

    type: Literal["register_listener"] = "register_listener"
    binding: SharedProxyBindingPayload


class DeregisterListenerRequest(BaseModel):
    """Remove one listener mode from the shared subprocess."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    type: Literal["deregister_listener"] = "deregister_listener"
    run_id: str = Field(alias="runId")


class SetOverridesRequest(BaseModel):
    """Replace override state for one run or track scope."""

    model_config = ConfigDict(frozen=True)

    type: Literal["set_overrides"] = "set_overrides"
    scope: OverrideScopePayload
    payload: OverrideSnapshotPayload


SharedProxyControlRequest = Annotated[
    PingRequest | RegisterListenerRequest | DeregisterListenerRequest | SetOverridesRequest,
    Field(discriminator="type"),
]


class SharedProxyControlAck(BaseModel):
    """Successful control-channel response."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    ok: Literal[True] = True
    proxy_generation: int = Field(default=0, alias="proxyGeneration", ge=0)
    mode_generation: int = Field(default=0, alias="modeGeneration", ge=0)
    overrides_generation: int = Field(default=0, alias="overridesGeneration", ge=0)


class SharedProxyControlErrorResponse(BaseModel):
    """Failed control-channel response."""

    model_config = ConfigDict(frozen=True)

    ok: Literal[False] = False
    code: str
    message: str


SharedProxyControlResponse = Annotated[
    SharedProxyControlAck | SharedProxyControlErrorResponse,
    Field(discriminator="ok"),
]

REQUEST_ADAPTER: TypeAdapter[SharedProxyControlRequest] = TypeAdapter(SharedProxyControlRequest)
RESPONSE_ADAPTER: TypeAdapter[SharedProxyControlResponse] = TypeAdapter(SharedProxyControlResponse)


def binding_payload_from_binding(binding: ProxyRunBinding) -> SharedProxyBindingPayload:
    """Build the serializable shared-proxy payload from the canonical binding."""

    run_id = require_run_id(binding.run_id)
    if binding.listen_port is None:
        msg = "listen_port is required for shared proxy registration"
        raise ValueError(msg)
    return SharedProxyBindingPayload(
        run_id=run_id,
        harness=binding.harness,
        working_dir=_string_path(binding.working_dir),
        storage_root=_storage_root(binding.storage),
        listen_port=binding.listen_port,
        upstream=binding.upstream,
        agent_home_dir=_string_path(binding.agent_home_dir),
        owned_native_session_id=binding.owned_native_session_id,
        owned_source_descriptor=binding.owned_source_descriptor,
        launch_fields=dict(binding.launch_fields),
        default_client_passthrough=tuple(binding.default_client_passthrough),
        breakpoint_skip_models=tuple(binding.breakpoint_skip_models),
        mode_kind=_infer_mode_kind(binding),
    )


def request_to_json_bytes(request: SharedProxyControlRequest) -> bytes:
    """Serialize one control request as a newline-framed JSON document."""

    return REQUEST_ADAPTER.dump_json(request, by_alias=True) + b"\n"


def response_to_json_bytes(
    response: SharedProxyControlAck | SharedProxyControlErrorResponse,
) -> bytes:
    """Serialize one control response as a newline-framed JSON document."""

    return response.model_dump_json(by_alias=True).encode() + b"\n"


def _infer_mode_kind(binding: ProxyRunBinding) -> ProxyModeKind:
    if binding.harness == "codex":
        return "regular"
    if binding.upstream:
        return "reverse"
    msg = "shared proxy binding needs harness='codex' or an upstream URL"
    raise ValueError(msg)


def _storage_root(storage: object) -> str | None:
    root = getattr(storage, "root", None)
    if root is None:
        return None
    if callable(root):
        return str(root())
    if isinstance(root, Path):
        return str(root)
    return str(root)


def _string_path(path: Path | None) -> str | None:
    return str(path) if path is not None else None
