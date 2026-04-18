Synced mirror of `~/.mdx/projects/manicure-codex-seam-audit.md`.

# Manicure Codex Seam Audit

## Summary

Manicure already has three useful provider seams:

- immutable IR plus override pipeline
- generic child process supervision
- a mostly provider neutral breakpoint editor that operates on IR, not raw JSON

The blockers for ChatGPT authenticated Codex are elsewhere. The live request path assumes an Anthropic HTTP POST to `/v1/messages`, the adapter contract only models raw request and response bodies, and token counting is wired directly to Anthropic headers and `/v1/messages/count_tokens`.

For ALP-1815, the correct product shape is a client specific launch path plus a transport specific capture layer. Codex should not be forced through the Claude reverse proxy model.

## Classification

| Area | Classification | Findings |
| --- | --- | --- |
| Launch and child process ownership | Extensible, with blocker | `ProcessSupervisor` is generic, but `manicure start` is Claude specific in CLI copy, binary resolution, system prompt injection, reverse proxy setup, and `ANTHROPIC_BASE_URL` export. References: `api/src/manicure/cli/__init__.py:153-200`, `api/src/manicure/cli/__init__.py:452-497`, `api/src/manicure/cli/runner.py:248-263`, `api/src/manicure/cli/prompt.py:1-63`, `api/src/manicure/supervisor.py:148-263`. |
| Adapter registry and IR | Real seam, but incomplete | `ProviderAdapter` and `get_adapter()` are real abstractions, and `InternalRequest` already preserves opaque provider fields. The contract is too narrow for WebSocket sessions because it only covers raw request and response bytes. References: `api/src/manicure/adapters/base.py:17-40`, `api/src/manicure/adapters/__init__.py:1-33`, `api/src/manicure/ir.py:44-64`, `api/src/manicure/ir.py:79-145`. |
| Addon transport entry | Anthropic specific blocker | `ManicureAddon.request()` exits unless the path starts with `/v1/messages`, before adapter selection even runs. ChatGPT Codex traffic will never hit the pipeline. References: `api/src/manicure/addon.py:439-446`, `api/src/manicure/adapters/anthropic.py:55-56`. |
| Breakpoint state and recount | Extensible, with blocker | Paused flow state is generic around IR, but recount stores Anthropic auth headers and reserializes through `AnthropicAdapter`. References: `api/src/manicure/breakpoint.py:24-42`, `api/src/manicure/api/v1/breakpoint_routes.py:14-15`, `api/src/manicure/api/v1/breakpoint_routes.py:36-55`. |
| Token counting | Anthropic specific blocker | Counting logic is explicitly built around Anthropic auth headers and `/v1/messages/count_tokens`. Exchange lazy recount uses `AnthropicAdapter()` directly. References: `api/src/manicure/counting.py:1-56`, `api/src/manicure/counting.py:105-130`, `api/src/manicure/api/v1/exchanges.py:12-18`, `api/src/manicure/api/v1/exchanges.py:107-205`. |
| Persistence and exchange API | Extensible, with blocker | Summary index fields are provider neutral, but stored artifacts only cover request and response blobs plus IR snapshots. There is no place for upgrade headers, initial request frame, or streamed upstream events. References: `api/src/manicure/storage/base.py:63-90`, `api/src/manicure/storage/disk.py:207-243`, `api/src/manicure/api/v1/exchanges.py:44-86`. |
| Override pipeline | Reusable | The override system already supports generic `sampling_set` and dotted `provider_extras_set` writes. That is enough for Codex specific request fields to flow through the existing rule pipeline once the request is normalized into IR. References: `api/src/manicure/overrides.py:30-73`, `api/src/manicure/overrides.py:372-482`, `api/src/manicure/overrides.py:676-870`. |
| Frontend editor and inspect surfaces | Mostly reusable | `BreakpointEditor`, `MessagesSection`, `SystemSection`, `ToolsSection`, and `InspectTab` all operate on generic IR plus override audit. The main Anthropic leak is the sampling overlay. References: `www/src/components/editor/BreakpointEditor.tsx:204-280`, `www/src/components/detail/InspectTab.tsx:131-180`, `www/src/types.ts:96-173`. |
| Sampling overlay | Anthropic specific, non blocker for transport | The overlay hard codes Anthropic `thinking`, `thinking.display`, and `output_config.effort` semantics. Codex can ship by gating this panel per provider, or by showing raw JSON first. References: `www/src/components/editor/SamplingSection.tsx:24-95`, `www/src/components/editor/SamplingSection.tsx:221-247`. |

## Reusable Seams

- `ProcessSupervisor.spawn()` already supports foreground PTY children and background log owned daemons. That is enough for a Codex launcher once argv and env construction move behind a client specific builder. `api/src/manicure/supervisor.py:148-263`
- The IR is intentionally opaque in the right places. `provider_extras`, `provider_data`, and `UnknownBlock` give a Codex adapter somewhere to keep frame specific fields without widening the core models first. `api/src/manicure/ir.py:44-64`, `api/src/manicure/ir.py:79-145`, `api/src/manicure/ir.py:157-168`
- The override engine does not care which provider owns a field. `provider_extras_set` already supports dotted nested writes with safe deletion and path validation. `api/src/manicure/overrides.py:388-482`
- The breakpoint editor is centered on `InternalRequest`. Messages, tools, system parts, and the raw JSON tab can all be reused for Codex once the paused flow exposes a normalized request. `www/src/components/editor/BreakpointEditor.tsx:245-280`
- Inspect view is already audit driven and reuses the same editor sections in read only mode. That should survive a second provider with minimal change. `www/src/components/detail/InspectTab.tsx:131-180`

## Blocking Refactors

### 1. Introduce a transport session seam above adapters

Current adapter methods only handle:

- `inbound_request(raw_body)`
- `outbound_request(ir)`
- `inbound_response(raw_body, content_type)`

That is enough for plain HTTP request interception. It is not enough for:

- WebSocket upgrade metadata
- initial client frame capture
- pre-forward breakpoint hold on a session
- upstream event relay
- frame level artifact persistence

This seam belongs in `ALP-1818`. Without it, Codex support will end up as a special case bolted into `addon.py`.

References: `api/src/manicure/adapters/base.py:17-40`, `api/src/manicure/addon.py:439-493`

### 2. Split launcher construction by client runtime

The current launcher path assumes:

- a `claude` binary
- optional `--append-system-prompt`
- reverse proxy mode
- `ANTHROPIC_BASE_URL=http://localhost:<port>`

ChatGPT authenticated Codex needs:

- a `codex` binary or equivalent session command
- explicit HTTPS proxy env
- `CODEX_CA_CERTIFICATE`
- no dependence on `ANTHROPIC_BASE_URL`

This is the core of `ALP-1816` and `ALP-1817`.

References: `api/src/manicure/cli/__init__.py:153-200`, `api/src/manicure/cli/__init__.py:452-497`, `api/src/manicure/cli/runner.py:248-263`, `api/src/manicure/cli/prompt.py:1-63`

### 3. Decouple token counting from Anthropic

Today the code assumes that token counts come from Anthropic and are available through stored Anthropic auth headers:

- `_AUTH_HEADER_KEYS` only knows Anthropic headers
- `_COUNT_PATH` is Anthropic specific
- paused flow recount instantiates `AnthropicAdapter()`
- exchange lazy recount instantiates `AnthropicAdapter()`

For Codex, token counts should be optional unless a provider specific counter exists. The breakpoint editor and exchange detail APIs already tolerate `null`, so the clean path is a provider aware counting contract with a safe unavailable state.

References: `api/src/manicure/counting.py:26-56`, `api/src/manicure/counting.py:105-130`, `api/src/manicure/api/v1/breakpoint_routes.py:36-55`, `api/src/manicure/api/v1/exchanges.py:107-205`, `api/src/manicure/breakpoint.py:34-38`

### 4. Expand persisted artifact shape for streamed transport

`ExchangeArtifacts` and `DiskStorageBackend.write_exchange()` currently write:

- `request.raw`
- `request.ir.json`
- `request.curated.ir.json`
- `response.raw`
- `response.ir.json`

Codex support needs at least:

- client upgrade request metadata
- upstream upgrade response metadata
- initial `response.create` frame
- normalized IR snapshots
- forwarded edited request frame
- streamed upstream event capture or summary

This should be part of `ALP-1822`, but its shape should be designed together with `ALP-1818` through `ALP-1820`.

References: `api/src/manicure/storage/base.py:81-90`, `api/src/manicure/storage/disk.py:207-243`

## Non Blocking Anthropic Residue

- `SamplingSection` should not be reused unchanged for Codex. It assumes Anthropic `thinking` and `output_config.effort` structures. Gate it on provider, or replace it with a generic provider extras editor for Codex V1. `www/src/components/editor/SamplingSection.tsx:24-95`, `www/src/components/editor/SamplingSection.tsx:221-247`
- CLI help, banner text, and injected prompt copy are Claude centric. This should be updated as part of the Codex launcher work, not before. `api/src/manicure/cli/help.py:24-110`, `api/src/manicure/cli/prompt.py:1-63`

## Recommended Issue Sequencing

The current checklist order is still workable. The important adjustment is ownership:

1. `ALP-1816` should own the launch abstraction for a Codex child process. Keep this focused on child argv and env construction, not transport parsing.
2. `ALP-1817` should add merged CA bundle generation and process scoped trust wiring.
3. `ALP-1818` must own the transport seam expansion above adapters. This is where WebSocket upgrade handling, initial frame capture, and provider aware session metadata should land.
4. `ALP-1819` should map the initial `response.create` frame into `InternalRequest`, leaning on `provider_extras` for fields that do not deserve first class IR slots yet.
5. `ALP-1820` should round trip edited IR back into the outbound request frame.
6. `ALP-1821` should reuse the existing Messages, System, Tools, and Raw tabs first. Treat the sampling overlay as provider gated.
7. `ALP-1822` should persist WebSocket transport artifacts and expose them through exchange detail APIs.
8. `ALP-1823` should add fixtures and diagnostics after the transport seam stabilizes.

## Concrete Guidance For The Next Worker

- Do not try to bolt Codex onto the existing `/v1/messages` branch in `ManicureAddon.request()`. Start by making transport dispatch happen before Anthropic specific path gating.
- Do not let `ANTHROPIC_BASE_URL` or reverse proxy mode define the Codex launcher architecture. ChatGPT authenticated Codex needs an explicit HTTPS proxy path.
- Treat API key mode as a harness only. The product path remains `wss://chatgpt.com/backend-api/codex/responses`.
