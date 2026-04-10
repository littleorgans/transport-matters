# manicure

> **mani**fest + **cur**at**e**. Care for the cargo your coding agent carries.

A provider-neutral context control plane for coding agents. Sits as a reverse proxy in front of Claude (V1) and Codex (V2), captures every `/v1/messages` exchange, normalises payloads into an internal representation, runs them through a deterministic curation pipeline, and optionally pauses for manual editing in a schema-aware editor.

No cert install. No system proxy settings. No sudo.

---

## Why

A single Claude Code session routinely sends 285 KB payloads — 147 tools, 3 system parts, 5 message turns. Tools alone account for 67% of that. Manicure gives you visibility into what's being sent, a pipeline to strip and rewrite it, and a breakpoint to intervene before it hits the API.

## Quick start

> Not yet released. See [Development](#development) to run from source.

```bash
# Install
curl -fsSL https://manicure.sh/install.sh | bash

# Start the workbench
manicure start

# In another terminal, point Claude Code at it
ANTHROPIC_BASE_URL=http://localhost:8787 claude
```

Open `http://localhost:8788`. Every request now flows through the workbench. Arm the breakpoint to pause and edit the next request before it forwards.

---

## Architecture

```
client
  └─ ANTHROPIC_BASE_URL=http://localhost:8787
        │
        ▼
   mitmproxy (reverse proxy → api.anthropic.com)
        │
        ├─ ProviderAdapter       parse raw body → InternalRequest IR
        ├─ Pipeline              apply curation rules (strip, truncate, rewrite)
        ├─ Breakpoint            optional pause for manual editing
        └─ ProviderAdapter       serialise IR → raw body → forward
        │
        ▼
   FastAPI (localhost:8788)      live log, rules CRUD, breakpoint control
        │
        ▼
   React SPA                     log viewer, schema-aware editor, rules UI
```

**Ports**: `8787` reverse proxy | `8788` web UI.

**Storage**: `~/.manicure/exchanges/` — append-only `index.jsonl`, per-exchange directories, `rules.json`.

---

## V1 rule vocabulary

| Action | Effect |
|---|---|
| `strip_tools` | Remove tools by name, prefix, or regex |
| `strip_thinking` | Drop all thinking blocks |
| `strip_system_part` | Remove a specific system part by index |
| `truncate_system_part` | Truncate a system part to N chars |
| `truncate_tool_result` | Truncate tool results by age or size |
| `rewrite_tool_description` | Replace a tool's description |

Rules are scoped: `global`, `model`, `account_id`, `device_id`, or `session_id`.

---

## Development

Requires Python 3.12+, Node 20+, [`uv`](https://docs.astral.sh/uv/), [`pnpm`](https://pnpm.io/).

```bash
# Install dependencies
just install

# Run api + www in parallel
just dev

# Quality gates
just check        # format, lint, typecheck
just api test     # run tests
```

### Stack

| Layer | Choice |
|---|---|
| Proxy | mitmproxy, reverse proxy mode |
| Backend | FastAPI + uvicorn, embedded in mitmproxy's asyncio loop |
| Storage | `StorageBackend` ABC, `DiskStorageBackend` default |
| Frontend | Vite + React |

---

## Status

| Phase | Description | Status |
|---|---|---|
| 1 | IR models, Anthropic adapter, storage backend | Done |
| 2 | Embedded HTTP server, SSE live log, React viewer | Pending |
| 3 | Pipeline engine, rule engine, rules UI | Pending |
| 4 | Breakpoint mechanism, schema-aware editor | Pending |

---

## License

Apache 2.0
