# manicure

> **mani**fest + **cur**at**e**. Care for the cargo your coding agent carries.

A provider-neutral context control plane for coding agents. Sits as a reverse proxy in front of Claude, captures every `/v1/messages` exchange, normalises payloads into an internal representation, runs them through a deterministic curation pipeline, and optionally pauses for manual editing in a schema-aware editor.

No cert install. No system proxy settings. No sudo.

## Install

```bash
uv tool install manicure     # recommended
pipx install manicure        # alternative
```

Or via the bootstrap script (installs uv first if missing):

```bash
curl -fsSL https://github.com/srobinson/manicure/releases/latest/download/install.sh | bash
```

## Quick start

```bash
# One command: starts the proxy + Claude Code together
manicure start                # in the current directory
manicure start ~/my-project   # in a specific working directory

# Proxy-only (bring your own client)
manicure start --no-claude

# then in another terminal
ANTHROPIC_BASE_URL=http://localhost:8787 claude
```

## From source

For day to day contributor work, install the local checkout as an
editable uv tool:

```bash
just tool-install-editable
```

Then from any project directory:

```bash
manicure start
```

If you want to run directly from source without installing a tool, run
the API project explicitly:

```bash
uv run --project api manicure start
```

From the repo root, `just start` is equivalent and is the preferred
source run entry point.

To validate the packaged artifact instead of the editable checkout, build
and install the wheel separately before release.

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
