"""Anthropic provider adapter.

Translates between the Anthropic ``/v1/messages`` wire format and the
canonical IR.  The round-trip invariant holds:
``outbound_request(inbound_request(raw)) == raw`` (modulo key ordering).
"""

from __future__ import annotations

import json
from typing import Any  # Any: opaque provider blobs, JSON dicts

from transport_matters.adapters.base import ProviderAdapter
from transport_matters.ir import (
    ContentBlock,
    ImageBlock,
    InternalRequest,
    InternalResponse,
    Message,
    RequestMetadata,
    SamplingParams,
    SystemPart,
    TextBlock,
    ThinkingBlock,
    ToolDef,
    ToolResultBlock,
    ToolUseBlock,
    UnknownBlock,
    UsageStats,
)

# Top-level keys that are explicitly mapped into IR fields.
_MAPPED_REQUEST_KEYS = frozenset(
    {
        "model",
        "system",
        "tools",
        "messages",
        "metadata",
        "max_tokens",
        "temperature",
        "top_p",
        "top_k",
        "stop_sequences",
        "stream",
    }
)


def _extra_provider_data(
    raw: dict[str, Any],  # Any: raw JSON dict
    known: set[str],
) -> dict[str, Any] | None:
    """Capture unknown sibling fields into an opaque overflow dict, or None.

    Keeps fields the IR does not model so they survive an edit round-trip. The
    single capture point shared by every block and component parser.
    """
    extra = {k: raw[k] for k in sorted(set(raw) - known)}
    return extra or None


class AnthropicAdapter(ProviderAdapter):
    name = "anthropic"

    # ── matching ────────────────────────────────────────────────────

    def matches(self, flow: Any) -> bool:  # Any: mitmproxy flow object
        return hasattr(flow, "request") and flow.request.path.startswith("/v1/messages")

    # ── inbound request ─────────────────────────────────────────────

    def inbound_request(self, raw_body: bytes) -> InternalRequest:
        data: dict[str, Any] = json.loads(raw_body)  # Any: raw JSON

        model = (
            self._normalise_model(data["model"])
            if data.get("model")
            else "anthropic/unknown"
        )
        system = self._parse_system(data.get("system", []))
        tools = self._parse_tools(data.get("tools", []))
        messages = self._parse_messages(data.get("messages", []))
        metadata = self._parse_metadata(data.get("metadata"))
        sampling = self._parse_sampling(data)
        stream = data.get("stream", False)

        extras: dict[str, Any] = {  # Any: unknown provider fields
            k: v for k, v in data.items() if k not in _MAPPED_REQUEST_KEYS
        }

        return InternalRequest(
            model=model,
            provider="anthropic",
            system=system,
            tools=tools,
            messages=messages,
            sampling=sampling,
            metadata=metadata,
            stream=stream,
            provider_extras=extras,
        )

    # ── outbound request ────────────────────────────────────────────

    def outbound_request(self, ir: InternalRequest) -> bytes:
        data: dict[str, Any] = {}  # Any: building raw JSON

        # model: strip provider prefix
        data["model"] = self._denormalise_model(ir.model)

        # system
        if ir.system:
            data["system"] = [self._system_part_to_dict(sp) for sp in ir.system]

        # max_tokens (always required by Anthropic)
        data["max_tokens"] = ir.sampling.max_tokens

        # messages
        data["messages"] = [self._message_to_dict(m) for m in ir.messages]

        # optional sampling params
        if ir.sampling.temperature is not None:
            data["temperature"] = ir.sampling.temperature
        if ir.sampling.top_p is not None:
            data["top_p"] = ir.sampling.top_p
        if ir.sampling.top_k is not None:
            data["top_k"] = ir.sampling.top_k
        if ir.sampling.stop_sequences:
            data["stop_sequences"] = ir.sampling.stop_sequences

        # metadata
        meta_dict = self._metadata_to_dict(ir.metadata)
        if meta_dict:
            data["metadata"] = meta_dict

        # stream
        if ir.stream:
            data["stream"] = ir.stream

        # tools
        if ir.tools:
            data["tools"] = [self._tool_to_dict(t) for t in ir.tools]

        # provider_extras: restore verbatim
        data.update(ir.provider_extras)

        return json.dumps(data, separators=(",", ":"), sort_keys=True).encode()

    # ── inbound response ────────────────────────────────────────────

    def inbound_response(self, raw_body: bytes, content_type: str) -> InternalResponse:
        if "event-stream" in content_type:
            return self._inbound_response_sse(raw_body)
        data: dict[str, Any] = json.loads(raw_body)  # Any: raw JSON

        usage_raw = data.get("usage", {})
        usage = UsageStats(
            input_tokens=usage_raw.get("input_tokens", 0),
            output_tokens=usage_raw.get("output_tokens", 0),
            cache_read_input_tokens=usage_raw.get("cache_read_input_tokens", 0),
            cache_creation_input_tokens=usage_raw.get("cache_creation_input_tokens", 0),
        )

        content_blocks = self._parse_response_content(data.get("content", []))

        mapped_keys = {"id", "type", "model", "role", "stop_reason", "usage", "content"}
        extras: dict[str, Any] = {  # Any: unknown provider fields
            k: v for k, v in data.items() if k not in mapped_keys
        }

        return InternalResponse(
            id=data.get("id", ""),
            model=(
                self._normalise_model(data["model"])
                if data.get("model")
                else "anthropic/unknown"
            ),
            provider="anthropic",
            stop_reason=data.get("stop_reason"),
            usage=usage,
            content=content_blocks,
            provider_extras=extras,
        )

    def _inbound_response_sse(self, raw_body: bytes) -> InternalResponse:
        """Reconstruct InternalResponse from a buffered SSE stream."""
        msg_id = ""
        model = ""
        stop_reason: str | None = None
        usage = UsageStats()
        content_blocks: list[Any] = []  # Any: partially built block dicts
        block_buffers: dict[int, dict[str, Any]] = {}  # index → partial block

        for line in raw_body.decode(errors="replace").splitlines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload in ("[DONE]", ""):
                continue
            try:
                ev: dict[str, Any] = json.loads(payload)  # Any: raw SSE event
            except json.JSONDecodeError:
                continue

            ev_type = ev.get("type", "")
            if ev_type == "message_start":
                msg = ev.get("message", {})
                msg_id = msg.get("id", "")
                model = msg.get("model", "")
                u = msg.get("usage", {})
                usage = UsageStats(
                    input_tokens=u.get("input_tokens", 0),
                    cache_read_input_tokens=u.get("cache_read_input_tokens", 0),
                    cache_creation_input_tokens=u.get("cache_creation_input_tokens", 0),
                )
            elif ev_type == "content_block_start":
                idx = ev.get("index", 0)
                block_buffers[idx] = dict(ev.get("content_block", {}))
            elif ev_type == "content_block_delta":
                idx = ev.get("index", 0)
                delta = ev.get("delta", {})
                buf = block_buffers.setdefault(idx, {})
                delta_type = delta.get("type", "")
                if delta_type == "text_delta":
                    buf["text"] = buf.get("text", "") + delta.get("text", "")
                elif delta_type == "thinking_delta":
                    buf["thinking"] = buf.get("thinking", "") + delta.get(
                        "thinking", ""
                    )
                elif delta_type == "input_json_delta":
                    buf["_input_partial"] = buf.get("_input_partial", "") + delta.get(
                        "partial_json", ""
                    )
            elif ev_type == "content_block_stop":
                idx = ev.get("index", 0)
                buf = block_buffers.pop(idx, None)  # type: ignore[arg-type]
                if buf:
                    if "_input_partial" in buf:
                        try:
                            parsed = json.loads(buf.pop("_input_partial"))
                        except json.JSONDecodeError:
                            parsed = {}
                        # ToolUseBlock.input is a dict; a stream that decodes to
                        # a non-object must be wrapped, not passed through.
                        buf["input"] = (
                            parsed if isinstance(parsed, dict) else {"value": parsed}
                        )
                    content_blocks.append(buf)
            elif ev_type == "message_delta":
                delta = ev.get("delta", {})
                stop_reason = delta.get("stop_reason", stop_reason)
                u = ev.get("usage", {})
                usage = UsageStats(
                    input_tokens=usage.input_tokens,
                    output_tokens=u.get("output_tokens", usage.output_tokens),
                    cache_read_input_tokens=usage.cache_read_input_tokens,
                    cache_creation_input_tokens=usage.cache_creation_input_tokens,
                )

        parsed_blocks = self._parse_response_content(content_blocks)
        return InternalResponse(
            id=msg_id,
            model=self._normalise_model(model) if model else "anthropic/unknown",
            provider="anthropic",
            stop_reason=stop_reason,
            usage=usage,
            content=parsed_blocks,
        )

    # ── private helpers ─────────────────────────────────────────────

    @staticmethod
    def _normalise_model(model: str) -> str:
        if model.startswith("anthropic/"):
            return model
        return f"anthropic/{model}"

    @staticmethod
    def _denormalise_model(model: str) -> str:
        if model.startswith("anthropic/"):
            return model[len("anthropic/") :]
        return model

    # -- system --

    @staticmethod
    def _parse_system(
        raw: list[dict[str, Any]] | str,  # Any: raw JSON dicts
    ) -> list[SystemPart]:
        # Anthropic accepts `system` as a plain string or a list of parts.
        if isinstance(raw, str):
            return [SystemPart(text=raw)] if raw else []
        parts: list[SystemPart] = []
        for item in raw:
            parts.append(
                SystemPart(
                    type=item.get("type", "text"),
                    text=item.get("text", ""),
                    cache_hint=item.get("cache_control"),
                    provider_data=_extra_provider_data(
                        item, {"type", "text", "cache_control"}
                    ),
                )
            )
        return parts

    @staticmethod
    def _system_part_to_dict(sp: SystemPart) -> dict[str, Any]:  # Any: raw JSON
        d: dict[str, Any] = {"type": sp.type, "text": sp.text}  # Any: building JSON
        if sp.cache_hint is not None:
            d["cache_control"] = sp.cache_hint
        if sp.provider_data:
            d.update(sp.provider_data)
        return d

    # -- tools --

    @staticmethod
    def _parse_tools(raw: list[dict[str, Any]]) -> list[ToolDef]:  # Any: raw JSON dicts
        tools: list[ToolDef] = []
        for item in raw:
            tools.append(
                ToolDef(
                    name=item.get("name", ""),
                    description=item.get("description", ""),
                    input_schema=item.get("input_schema", {}),
                    provider_data=_extra_provider_data(
                        item, {"name", "description", "input_schema"}
                    ),
                )
            )
        return tools

    @staticmethod
    def _tool_to_dict(t: ToolDef) -> dict[str, Any]:  # Any: raw JSON
        d: dict[str, Any] = {  # Any: building JSON
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        if t.provider_data:
            d.update(t.provider_data)
        return d

    # -- messages --

    @classmethod
    def _parse_messages(
        cls, raw: list[dict[str, Any]]
    ) -> list[Message]:  # Any: raw JSON dicts
        messages: list[Message] = []
        for item in raw:
            raw_content = item.get("content", [])
            # Anthropic allows string content as shorthand
            if isinstance(raw_content, str):
                blocks: list[ContentBlock] = [TextBlock(text=raw_content)]
            else:
                blocks = [cls._parse_content_block(b) for b in raw_content]
            if blocks:
                messages.append(
                    Message(
                        role=item.get("role", "user"),
                        content=blocks,
                        provider_data=_extra_provider_data(item, {"role", "content"}),
                    )
                )
        return messages

    @classmethod
    def _parse_content_block(
        cls,
        raw: dict[str, Any],  # Any: raw JSON dict
    ) -> ContentBlock:
        # Each known-type branch requires its modeled keys; a known type missing
        # one falls through to UnknownBlock(raw=raw) (preserved verbatim) rather
        # than raising and dropping the whole request.
        block_type = raw.get("type", "unknown")
        if block_type == "text" and "text" in raw:
            return TextBlock(
                text=raw["text"],
                provider_data=_extra_provider_data(raw, {"type", "text"}),
            )
        if block_type == "tool_use" and {"id", "name", "input"} <= raw.keys():
            return ToolUseBlock(
                id=raw["id"],
                name=raw["name"],
                input=raw["input"],
                provider_data=_extra_provider_data(
                    raw, {"type", "id", "name", "input"}
                ),
            )
        if block_type == "tool_result" and "tool_use_id" in raw:
            raw_sub = raw.get("content", [])
            if isinstance(raw_sub, str):
                sub_content: list[TextBlock | ImageBlock | UnknownBlock] = [
                    TextBlock(text=raw_sub)
                ]
            else:
                sub_content = [cls._parse_tool_result_sub_block(s) for s in raw_sub]
            return ToolResultBlock(
                tool_use_id=raw["tool_use_id"],
                content=sub_content,
                is_error=raw.get("is_error", False),
                provider_data=_extra_provider_data(
                    raw, {"type", "tool_use_id", "content", "is_error"}
                ),
            )
        if block_type == "thinking":
            # Anthropic uses 'thinking' field in conversation history, 'text' in some
            # response contexts — accept both for robustness.
            text = raw.get("thinking") or raw.get("text", "")
            return ThinkingBlock(
                text=text,
                provider_data=_extra_provider_data(raw, {"type", "text", "thinking"}),
            )
        if block_type == "image" and "source" in raw:
            return ImageBlock(
                source=raw["source"],
                provider_data=_extra_provider_data(raw, {"type", "source"}),
            )
        return UnknownBlock(raw=raw)

    @staticmethod
    def _parse_tool_result_sub_block(
        sub: dict[str, Any],  # Any: raw JSON dict
    ) -> TextBlock | ImageBlock | UnknownBlock:
        sub_type = sub.get("type")
        if sub_type == "text" and "text" in sub:
            return TextBlock(
                text=sub["text"],
                provider_data=_extra_provider_data(sub, {"type", "text"}),
            )
        if sub_type == "image" and "source" in sub:
            return ImageBlock(
                source=sub["source"],
                provider_data=_extra_provider_data(sub, {"type", "source"}),
            )
        # Unknown or incomplete sub-block: preserve verbatim instead of a lossy
        # str() coercion or a KeyError that would drop the whole request.
        return UnknownBlock(raw=sub)

    @classmethod
    def _message_to_dict(cls, m: Message) -> dict[str, Any]:  # Any: raw JSON
        d: dict[str, Any] = {  # Any: building JSON
            "role": m.role,
            "content": [cls._content_block_to_dict(b) for b in m.content],
        }
        if m.provider_data:
            d.update(m.provider_data)
        return d

    @classmethod
    def _content_block_to_dict(
        cls,
        block: ContentBlock,
    ) -> dict[str, Any]:  # Any: raw JSON
        if isinstance(block, TextBlock):
            d: dict[str, Any] = {"type": "text", "text": block.text}  # Any: raw JSON
            if block.provider_data:
                d.update(block.provider_data)
            return d
        if isinstance(block, ToolUseBlock):
            d = {
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            }
            if block.provider_data:
                d.update(block.provider_data)
            return d
        if isinstance(block, ToolResultBlock):
            result: dict[str, Any] = {  # Any: raw JSON
                "type": "tool_result",
                "tool_use_id": block.tool_use_id,
                "content": [cls._content_block_to_dict(item) for item in block.content],
            }
            if block.is_error:
                result["is_error"] = block.is_error
            if block.provider_data:
                result.update(block.provider_data)
            return result
        if isinstance(block, ThinkingBlock):
            # Anthropic expects 'thinking' field name (not 'text') for round-trips
            d = {"type": "thinking", "thinking": block.text}
            if block.provider_data:
                d.update(block.provider_data)
            return d
        if isinstance(block, ImageBlock):
            d = {"type": "image", "source": block.source}
            if block.provider_data:
                d.update(block.provider_data)
            return d
        if isinstance(block, UnknownBlock):
            return block.raw
        return block.model_dump(mode="json")

    # -- metadata --

    @staticmethod
    def _parse_metadata(
        raw: dict[str, Any] | None,  # Any: raw JSON
    ) -> RequestMetadata:
        if not raw:
            return RequestMetadata()

        session_id: str | None = None
        device_id: str | None = None
        account_id: str | None = None

        user_id = raw.get("user_id")
        if isinstance(user_id, str):
            try:
                parsed = json.loads(user_id)
                if isinstance(parsed, dict):
                    session_id = parsed.get("session_id")
                    device_id = parsed.get("device_id")
                    account_id = parsed.get("account_id")
            except (json.JSONDecodeError, TypeError):
                pass

        return RequestMetadata(
            session_id=session_id,
            device_id=device_id,
            account_id=account_id,
            provider_metadata=raw,
        )

    @staticmethod
    def _metadata_to_dict(meta: RequestMetadata) -> dict[str, Any]:  # Any: raw JSON
        return dict(meta.provider_metadata)

    # -- sampling --

    @staticmethod
    def _parse_sampling(data: dict[str, Any]) -> SamplingParams:  # Any: raw JSON
        return SamplingParams(
            max_tokens=data.get("max_tokens", 0),
            temperature=data.get("temperature"),
            top_p=data.get("top_p"),
            top_k=data.get("top_k"),
            stop_sequences=data.get("stop_sequences", []),
        )

    # -- response content --

    @classmethod
    def _parse_response_content(
        cls,
        raw: list[dict[str, Any]],  # Any: raw JSON dicts
    ) -> list[TextBlock | ToolUseBlock | ThinkingBlock | UnknownBlock]:
        blocks: list[TextBlock | ToolUseBlock | ThinkingBlock | UnknownBlock] = []
        for item in raw:
            block_type = item.get("type", "unknown")
            if block_type == "text" and "text" in item:
                blocks.append(
                    TextBlock(
                        text=item["text"],
                        provider_data=_extra_provider_data(item, {"type", "text"}),
                    )
                )
            elif block_type == "tool_use" and {"id", "name", "input"} <= item.keys():
                blocks.append(
                    ToolUseBlock(
                        id=item["id"],
                        name=item["name"],
                        input=item["input"],
                        provider_data=_extra_provider_data(
                            item, {"type", "id", "name", "input"}
                        ),
                    )
                )
            elif block_type == "thinking":
                # Anthropic uses 'thinking' field in the JSON wire format and
                # SSE-buffered blocks; some historical payloads use 'text'.
                # Accept both for parity with _parse_content_block.
                text = item.get("thinking") or item.get("text", "")
                blocks.append(
                    ThinkingBlock(
                        text=text,
                        provider_data=_extra_provider_data(
                            item, {"type", "text", "thinking"}
                        ),
                    )
                )
            else:
                blocks.append(UnknownBlock(raw=item))
        return blocks
