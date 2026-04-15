# manicure

> Care for the cargo your coding agent carries.

A reverse proxy for Claude Code. It sits between your agent and `api.anthropic.com`, captures every `/v1/messages` exchange, renders it in a web UI, and optionally pauses at a breakpoint so you can edit the payload before it forwards. No cert install. No system proxy. No sudo.

---

## Install

```bash
curl -fsSL https://github.com/srobinson/manicure/releases/latest/download/install.sh | bash

# Or, if you already have uv:
uv tool install manicure
```

Verify:

```bash
manicure doctor
```

---

## Quick start

```bash
# Proxy + Claude Code in the current directory
manicure start

# In a specific working directory
manicure start ~/my-project

# Proxy only, run your own client
manicure start --no-claude
```

---

## Architecture

```
client
  └─ ANTHROPIC_BASE_URL=http://localhost:{proxy_port}
        │
        ▼
   mitmproxy (reverse proxy → api.anthropic.com)
        │
        ├─ ProviderAdapter       parse raw body → InternalRequest IR
        ├─ Breakpoint            optional pause for manual editing
        ├─ OverrideStore         apply session-scoped overrides
        └─ ProviderAdapter       serialise IR → raw body → forward
        │
        ▼
   FastAPI (localhost:{web_port})   live log, breakpoint control, overrides CRUD
        │
        ▼
   React SPA                        log viewer, schema-aware editor
```
---

### Stack

| Layer | Choice |
|---|---|
| Proxy | mitmproxy, reverse proxy mode |
| Backend | FastAPI + uvicorn, embedded in mitmproxy's asyncio loop |
| Storage | `StorageBackend` ABC, `DiskStorageBackend` default |
| Frontend | Vite + React |

---

## License

Apache 2.0
