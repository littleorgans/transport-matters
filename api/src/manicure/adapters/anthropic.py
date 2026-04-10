"""Anthropic provider adapter.

Translates between the Anthropic ``/v1/messages`` wire format and the
canonical IR.  The round-trip invariant holds:
``outbound_request(inbound_request(raw)) == raw`` (modulo key ordering).
"""

from __future__ import annotations

import json
from typing import Any  # Any: opaque provider blobs, JSON dicts

from manicure.adapters.base import ProviderAdapter
from manicure.ir import (
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


class AnthropicAdapter(ProviderAdapter):
    name = "anthropic"

    # ── matching ────────────────────────────────────────────────────

    def matches(self, flow: Any) -> bool:  # Any: mitmproxy flow object
        return hasattr(flow, "request") and flow.request.path.startswith("/v1/messages")

    # ── inbound request ─────────────────────────────────────────────

    def inbound_request(self, raw_body: bytes) -> InternalRequest:
        data: dict[str, Any] = json.loads(raw_body)  # Any: raw JSON

        model = self._normalise_model(data["model"])
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
            id=data["id"],
            model=self._normalise_model(data["model"]),
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
                            buf["input"] = json.loads(buf.pop("_input_partial"))
                        except json.JSONDecodeError:
                            buf["input"] = {}
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
        raw: list[dict[str, Any]],
    ) -> list[SystemPart]:  # Any: raw JSON dicts
        parts: list[SystemPart] = []
        for item in raw:
            cache_hint = item.get("cache_control")
            provider_data: dict[str, Any] | None = None  # Any: extra fields
            extra_keys = set(item.keys()) - {"type", "text", "cache_control"}
            if extra_keys:
                provider_data = {k: item[k] for k in extra_keys}
            parts.append(
                SystemPart(
                    type=item.get("type", "text"),
                    text=item["text"],
                    cache_hint=cache_hint,
                    provider_data=provider_data,
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
            provider_data: dict[str, Any] | None = None  # Any: extra fields
            extra_keys = set(item.keys()) - {"name", "description", "input_schema"}
            if extra_keys:
                provider_data = {k: item[k] for k in sorted(extra_keys)}
            tools.append(
                ToolDef(
                    name=item["name"],
                    description=item["description"],
                    input_schema=item["input_schema"],
                    provider_data=provider_data,
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
            messages.append(Message(role=item["role"], content=blocks))
        return messages

    @staticmethod
    def _parse_content_block(
        raw: dict[str, Any],  # Any: raw JSON dict
    ) -> ContentBlock:
        block_type = raw.get("type", "unknown")
        if block_type == "text":
            return TextBlock(text=raw["text"])
        if block_type == "tool_use":
            return ToolUseBlock(id=raw["id"], name=raw["name"], input=raw["input"])
        if block_type == "tool_result":
            sub_content: list[TextBlock | ImageBlock] = []
            raw_sub = raw.get("content", [])
            if isinstance(raw_sub, str):
                sub_content = [TextBlock(text=raw_sub)]
            else:
                for sub in raw_sub:
                    if sub.get("type") == "text":
                        sub_content.append(TextBlock(text=sub["text"]))
                    elif sub.get("type") == "image":
                        sub_content.append(ImageBlock(source=sub["source"]))
                    else:
                        # Treat unknown sub-blocks as text if they have text
                        sub_content.append(TextBlock(text=str(sub)))
            return ToolResultBlock(
                tool_use_id=raw["tool_use_id"],
                content=sub_content,
                is_error=raw.get("is_error", False),
            )
        if block_type == "thinking":
            # Anthropic uses 'thinking' field in conversation history, 'text' in some
            # response contexts — accept both for robustness.
            text = raw.get("thinking") or raw.get("text", "")
            provider_data: dict[str, Any] | None = None  # Any: extra fields
            extra_keys = set(raw.keys()) - {"type", "text", "thinking"}
            if extra_keys:
                provider_data = {k: raw[k] for k in sorted(extra_keys)}
            return ThinkingBlock(text=text, provider_data=provider_data)
        if block_type == "image":
            return ImageBlock(source=raw["source"])
        return UnknownBlock(raw=raw)

    @classmethod
    def _message_to_dict(cls, m: Message) -> dict[str, Any]:  # Any: raw JSON
        return {
            "role": m.role,
            "content": [cls._content_block_to_dict(b) for b in m.content],
        }

    @classmethod
    def _content_block_to_dict(
        cls,
        block: ContentBlock,
    ) -> dict[str, Any]:  # Any: raw JSON
        if isinstance(block, TextBlock):
            return {"type": "text", "text": block.text}
        if isinstance(block, ToolUseBlock):
            return {
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            }
        if isinstance(block, ToolResultBlock):
            sub: list[dict[str, Any]] = []  # Any: raw JSON
            for item in block.content:
                if isinstance(item, TextBlock):
                    sub.append({"type": "text", "text": item.text})
                elif isinstance(item, ImageBlock):
                    sub.append({"type": "image", "source": item.source})
            result: dict[str, Any] = {  # Any: raw JSON
                "type": "tool_result",
                "tool_use_id": block.tool_use_id,
                "content": sub,
            }
            if block.is_error:
                result["is_error"] = block.is_error
            return result
        if isinstance(block, ThinkingBlock):
            # Anthropic expects 'thinking' field name (not 'text') for round-trips
            d: dict[str, Any] = {
                "type": "thinking",
                "thinking": block.text,
            }  # Any: raw JSON
            if block.provider_data:
                d.update(block.provider_data)
            return d
        if isinstance(block, ImageBlock):
            return {"type": "image", "source": block.source}
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
            max_tokens=data["max_tokens"],
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
            if block_type == "text":
                blocks.append(TextBlock(text=item["text"]))
            elif block_type == "tool_use":
                blocks.append(
                    ToolUseBlock(id=item["id"], name=item["name"], input=item["input"])
                )
            elif block_type == "thinking":
                provider_data: dict[str, Any] | None = None  # Any: extra fields
                extra_keys = set(item.keys()) - {"type", "text"}
                if extra_keys:
                    provider_data = {k: item[k] for k in sorted(extra_keys)}
                blocks.append(
                    ThinkingBlock(text=item["text"], provider_data=provider_data)
                )
            else:
                blocks.append(UnknownBlock(raw=item))
        return blocks
