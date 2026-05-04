# Lazy Tool Loading — Design Sketch

## The core idea in one paragraph

The proxy strips the full tool definitions out of every upstream request. In their place it injects a compact **catalog** (names + one-line descriptions) into a cacheable system part, and a single `activate_tool` meta-tool. The model reads the catalog, calls `activate_tool(name)` when it needs a capability, and the proxy resolves the activation invisibly by looping a second upstream call with the full definition now in the tools list. Per-session state tracks which tools are already active so subsequent turns in the same session pay for them once.

## What goes over the wire

### 1. The catalog system part

A new `SystemPart` injected at the end of `ir.system`. Cacheable, rarely changes, gets a cache hint so Anthropic's prompt caching picks it up after the first turn.

```
AVAILABLE TOOLS (call `activate_tool(name)` to use any of these):
- Bash: Executes a given bash command and returns its output.
- Edit: Performs exact string replacements in files.
- Read: Reads a file from the local filesystem.
- Grep: A powerful search tool built on ripgrep.
- WebFetch: Fetches content from a specified URL.
- ...
```

The one-line description is the first sentence of the full tool description. For 147 tools averaging 80 chars each that's ~12 KB. With prompt caching on the system part it's effectively free after turn one.

### 2. The activate_tool meta-definition

Injected as the first (and possibly only) entry in `ir.tools` on the upstream request. Small, always present.

```json
{
  \"name\": \"activate_tool\",
  \"description\": \"Activate a tool from the catalog so you can use it in subsequent turns. Call this when you need a capability that is listed in AVAILABLE TOOLS but is not yet in your active tool set. You can activate multiple tools in sequence.\",
  \"input_schema\": {
    \"type\": \"object\",
    \"properties\": {
      \"name\": {
        \"type\": \"string\",
        \"description\": \"Exact tool name from the catalog\"
      }
    },
    \"required\": [\"name\"]
  }
}
```

### 3. The active set

For every session, the proxy maintains a set of activated tool names. On each upstream request, the full `ToolDef` for each name in the active set is appended to `ir.tools` alongside `activate_tool`. At session start the set is empty, so the first upstream request ships only `activate_tool` plus the catalog, and the model picks what it needs.

## Module layout

New module: `api/src/transport_matters/dynamic_tools.py`. Sits in the DAG between `rules` and `pipeline` (or alongside `pipeline` as a parallel stage — see \"Where it runs\" below).

```
ir → adapters → rules → pipeline → dynamic_tools → breakpoint → server
                                        ↑
                                   (new stage)
```

No new dependency on anything except `ir` and a state store. Pure transformation plus a stateful activation ledger.

## Key types

```python
# api/src/transport_matters/dynamic_tools.py

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from transport_matters.ir import (
    InternalRequest,
    InternalResponse,
    SystemPart,
    ToolDef,
    ToolUseBlock,
    Message,
    ToolResultBlock,
    TextBlock,
)


class CatalogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    summary: str          # first sentence of the original description
    full_def: ToolDef     # kept out of band, injected on activation


class DynamicToolsConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    enabled: bool = True
    max_activations_per_request: int = 5
    min_catalog_size: int = 10       # don't bother lazy-loading small tool sets
    cache_catalog_system_part: bool = True


class SessionActivation(BaseModel):
    session_id: str
    active_tools: set[str] = Field(default_factory=set)
```

## The state store

Small ABC, same shape as `StorageBackend`. In-memory default for v1, SQLite fallback optional.

```python
class ActivationStore(ABC):
    @abstractmethod
    def get(self, session_id: str) -> set[str]: ...
    @abstractmethod
    def add(self, session_id: str, tool_name: str) -> None: ...
    @abstractmethod
    def clear(self, session_id: str) -> None: ...
```

Persists nothing by default. The worst case on restart is that the model re-activates what it needs. Cheap and recoverable.

## The request-side transform

Pure-ish function. Reads the active set, rewrites the IR to use the catalog + meta-tool + active definitions only.

```python
def transform_request(
    ir: InternalRequest,
    config: DynamicToolsConfig,
    store: ActivationStore,
) -> tuple[InternalRequest, CatalogMap]:
    \"\"\"Strip full tools, inject catalog + activate_tool + active set.

    Returns the rewritten IR and a CatalogMap (name -> full ToolDef) used
    later by the response observer to resolve activations.
    \"\"\"
    if not config.enabled:
        return ir, {}
    if len(ir.tools) < config.min_catalog_size:
        return ir, {}
    if ir.metadata.session_id is None:
        return ir, {}  # no session identity, fall back to static tools

    catalog_map: dict[str, ToolDef] = {t.name: t for t in ir.tools}
    catalog_text = _render_catalog(ir.tools)

    active_names = store.get(ir.metadata.session_id)
    active_defs = [catalog_map[n] for n in active_names if n in catalog_map]

    new_system = list(ir.system) + [
        SystemPart(
            type=\"text\",
            text=catalog_text,
            cache_hint={\"type\": \"ephemeral\"} if config.cache_catalog_system_part else None,
        )
    ]
    new_tools = [_ACTIVATE_TOOL_DEF] + active_defs

    new_ir = ir.model_copy(update={\"system\": new_system, \"tools\": new_tools})
    return new_ir, catalog_map
```

`_render_catalog` strips each tool down to `- name: first_sentence(description)`. `_ACTIVATE_TOOL_DEF` is a module-level constant.

## The response-side observer and activation loop

This is the part that makes it transparent to the client. The proxy intercepts the response, and if the model called `activate_tool`, the proxy handles the tool result itself and loops another upstream call before returning anything to the client.

```python
def contains_activation(response: InternalResponse) -> list[str]:
    \"\"\"Return the list of tool names the model asked to activate, in order.\"\"\"
    names: list[str] = []
    for block in response.content:
        if isinstance(block, ToolUseBlock) and block.name == \"activate_tool\":
            name = block.input.get(\"name\")
            if isinstance(name, str):
                names.append(name)
    return names


def apply_activations(
    ir: InternalRequest,
    response: InternalResponse,
    catalog_map: CatalogMap,
    store: ActivationStore,
) -> InternalRequest:
    \"\"\"Build the continuation request after the model activated tools.

    - Records activations in the store.
    - Appends the assistant response + synthetic tool_results to messages.
    - Rewrites tools list to include the newly-activated definitions.
    \"\"\"
    session_id = ir.metadata.session_id
    assert session_id is not None  # guarded upstream

    # Append the assistant message as-is
    assistant_msg = Message(role=\"assistant\", content=response.content)

    # Build synthetic tool_results for each activate_tool call in order
    tool_results: list[ToolResultBlock] = []
    for block in response.content:
        if isinstance(block, ToolUseBlock) and block.name == \"activate_tool\":
            name = block.input.get(\"name\", \"\")
            if name in catalog_map:
                store.add(session_id, name)
                result_text = f\"Tool '{name}' activated.\"
            else:
                result_text = (
                    f\"Tool '{name}' not in catalog. \"
                    f\"Available: {', '.join(sorted(catalog_map.keys())[:20])}...\"
                )
            tool_results.append(
                ToolResultBlock(
                    type=\"tool_result\",
                    tool_use_id=block.id,
                    content=[TextBlock(type=\"text\", text=result_text)],
                    is_error=name not in catalog_map,
                )
            )

    user_msg = Message(role=\"user\", content=tool_results)

    new_messages = list(ir.messages) + [assistant_msg, user_msg]

    # Rebuild tools with newly activated set
    active_names = store.get(session_id)
    active_defs = [catalog_map[n] for n in active_names if n in catalog_map]
    new_tools = [_ACTIVATE_TOOL_DEF] + active_defs

    return ir.model_copy(update={\"messages\": new_messages, \"tools\": new_tools})
```

## Where it runs in the request lifecycle

This is the part that touches `addon.py` (the mitmproxy hook). The existing flow is roughly:

```
request_hook:
  raw → adapter.parse_request → IR → pipeline.apply(rules) → breakpoint → adapter.serialize → forward
```

New flow:

```
request_hook:
  raw → adapter.parse_request → IR
       → pipeline.apply(rules)
       → dynamic_tools.transform_request  ← new
       → breakpoint
       → adapter.serialize → forward
       (save catalog_map on the exchange for the response hook)

response_hook:
  raw → adapter.parse_response → response IR
      → dynamic_tools.contains_activation?
         yes:
           → dynamic_tools.apply_activations
           → adapter.serialize request (again)
           → forward internally
           → loop up to max_activations_per_request
         no:
           → return to client
```

The activation loop is the new complexity. It lives inside the response hook (or just after it) and makes N additional upstream calls before the client ever sees a response. Each loop iteration is a real round trip to Anthropic, so latency = base_latency * (1 + num_activations). In practice num_activations is 0 or 1 per client request after the first few turns.

## Audit surface

`PipelineAudit` already tracks `rules_applied` and `chars_before/after`. Add a parallel `DynamicToolsAudit` so the workbench UI can show:

```python
class DynamicToolsAudit(BaseModel):
    catalog_size: int              # tools in catalog
    active_before: int             # tools active before this request
    active_after: int              # tools active after activation loop
    activations_this_request: list[str]
    chars_saved: int               # vs. shipping all tools
    upstream_calls: int            # including activation continuations
```

Stored on the exchange record. The UI can render \"Saved 183 KB by lazy-loading tools, 2 activations, 3 upstream calls.\"

## The request-lifecycle diagram, in text

```
client
  └─ POST /v1/messages (147 tools)
       │
       ▼
  adapter.parse_request → IR (147 tools, session=abc)
       │
       ▼
  pipeline.apply(rules) → IR (147 tools still)
       │
       ▼
  dynamic_tools.transform_request
       │  (strips 147 tools, injects catalog sysprt + activate_tool + active[])
       ▼
  IR (1 tool: activate_tool, catalog in system)
       │
       ▼
  adapter.serialize → upstream request
       │
       ▼
  anthropic api ──── model decides: \"I need Bash\"
       │
       ▼
  response: ToolUseBlock(name=activate_tool, input={name: \"Bash\"})
       │
       ▼
  dynamic_tools.contains_activation → [\"Bash\"]
       │
       ▼
  dynamic_tools.apply_activations
       │  (store.add(abc, \"Bash\"); synthesize tool_result; rebuild IR)
       ▼
  IR (2 tools: activate_tool + Bash)
       │
       ▼
  adapter.serialize → upstream request (continuation)
       │
       ▼
  anthropic api ──── model now calls Bash
       │
       ▼
  response: ToolUseBlock(name=Bash, input={command: \"ls\"})
       │
       ▼
  dynamic_tools.contains_activation → []
       │
       ▼
  return to client
```

## Rule vs stage

I thought about modelling this as a new rule action (`lazy_load_tools`) and keeping `rules.py` as the single curation surface. The stateful activation ledger breaks the pure-function contract of existing actions, and the response observer has no place to hook in from a rule. Cleanest to make it its own stage beside the rule pipeline, not a rule.

The workbench UI can still expose a \"Dynamic Tools: on/off\" toggle that maps to `DynamicToolsConfig.enabled`, so users don't care about the architectural distinction.

## Design decisions for the spike

| Decision | v1 choice | Why |
|---|---|---|
| Catalog format | one line per tool, first sentence of description | cheap, readable, model-friendly |
| Catalog location | last system part, cacheable | prompt cache reuse |
| Activation semantics | sticky for session lifetime | simplest, matches how people work in a single session |
| Storage | in-memory dict keyed by session_id | cheap, recoverable |
| Max continuations | 5 per client request | bounds the loop, enough for typical activations |
| Session missing | skip dynamic tools, fall back to static | don't break clients that don't set session_id |
| Catalog < 10 tools | skip dynamic tools | not worth the roundtrip overhead |
| Unknown tool in activate_tool call | return error tool_result, continue loop | model self-corrects |

## Open questions worth thinking about during the spike

1. **Prompt tuning for reliable activation**. Current models aren't trained for this pattern. You will need an upfront system instruction that explicitly teaches the convention. Something like \"Before calling any tool that is not already in your tool list, call activate_tool with the tool's name from AVAILABLE TOOLS. activate_tool is a free operation and the tool becomes usable immediately.\" Tune this against real Claude Code sessions.

2. **Cold start latency**. The first time the model needs a tool, it pays one extra roundtrip. For a session that activates 3 tools across the first 5 turns, that's 3 extra roundtrips total, amortised across dozens of turns after. Worth measuring.

3. **Claude Code does not cache system parts it did not send**. Transport Matters is inserting a new system part the client did not author. The cache_hint on that part will only work if the adapter emits it correctly in the Anthropic wire format. Worth verifying against the provider_data round-trip behaviour already in the adapter.

4. **Streaming**. If the upstream response is streamed, the activation loop has to wait for the full response before it can detect `activate_tool` and loop. That means the client sees no tokens until all activations resolve. For fast activations this is imperceptible. For slow ones, it is noticeable. Consider: do you stream the final response only, or do you stream \"pass-through\" until you hit the first activate_tool block?

5. **Tool use ID collision**. The synthesized tool_result uses the real tool_use id from the model's response, which the client never sees. Safe as long as no downstream consumer cross-references these ids.

6. **Measuring savings**. The audit needs to know what the static baseline would have been so you can show \"you saved N KB vs the static version.\" Easy: count chars of the stripped tools in `transform_request`, store on the audit.

## Testing strategy for the spike

Three test layers, same pattern as the existing codebase:

- **Unit** (`test_dynamic_tools.py` colocated). Test `transform_request`, `contains_activation`, `apply_activations` as pure functions against fixture IRs.
- **Integration**. Spin up the proxy with a mocked upstream that replays canned activate_tool responses, verify the loop, verify the final response to the client is clean.
- **End to end** once the spike is real. Point Claude Code at it, run a session, measure chars saved and wall-clock latency delta.

## What I would build first

In order, smallest viable slices:

1. `dynamic_tools.py` with `transform_request`, the catalog renderer, and the activate_tool constant. Unit tests. No response handling yet. At this point, if you point Claude Code at it, the model will try to call activate_tool and the client will error, but you can verify the outgoing request is tiny.
2. In-memory `ActivationStore`.
3. `contains_activation` and `apply_activations`. Unit tests.
4. The activation loop in `addon.py`. Integration test with mocked upstream.
5. `DynamicToolsAudit` and storage integration.
6. Tuning pass on the system instruction that teaches the model to call activate_tool.
7. Measure. Screenshot the before/after. This becomes the Show HN.

---

That is the sketch. Want me to go one level deeper on any piece, or start implementing the first slice (`dynamic_tools.py` with `transform_request` + unit tests) so you can see the shape land in code?