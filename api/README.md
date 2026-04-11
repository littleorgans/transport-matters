# manicure

> **mani**fest + **cur**at**e**. Care for the cargo your coding agent carries.

A provider-neutral context control plane for coding agents. Sits as a reverse proxy in front of Claude, captures every `/v1/messages` exchange, normalises payloads into an internal representation, runs them through a deterministic curation pipeline, and optionally pauses for manual editing in a schema-aware editor.

No cert install. No system proxy settings. No sudo.

## Install

```bash
curl -fsSL https://manicure.sh/install.sh | bash
```

Or install directly from PyPI:

```bash
uv tool install manicure     # recommended
pipx install manicure        # alternative
```

## Quick start

```bash
# Start the workbench (proxy + web UI)
manicure start

# In another terminal, point your coding agent at it
ANTHROPIC_BASE_URL=http://localhost:8787 claude
```

Open `http://localhost:8788` to see the live log, the rules UI, and the breakpoint editor.

## What it does

Every `/v1/messages` request your agent sends gets:

1. **Captured** — full request and response, logged to `~/.manicure/exchanges/`.
2. **Curated** — a deterministic pipeline applies your rules (strip tools, truncate system parts, rewrite descriptions, drop thinking blocks).
3. **Paused** (optional) — arm the breakpoint to edit the next request in a schema-aware editor before it forwards upstream.

All visible in a web UI at `http://localhost:8788`.

## Why

A single Claude Code session routinely sends 285 KB payloads: 147 tools, 3 system parts, 5 message turns. Tools alone account for 67% of that. Manicure gives you visibility into what's being sent, a pipeline to strip and rewrite it, and a breakpoint to intervene before it hits the API.

## Documentation

Full docs, architecture, and contributing guide: <https://github.com/srobinson/manicure>

## License

Apache 2.0. See [LICENSE](LICENSE).
