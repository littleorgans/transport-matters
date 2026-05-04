# Mitmproxy integration — the lowdown

## The one-sentence model

Transport Matters runs the FastAPI web UI **inside mitmproxy's own asyncio event loop**. A single `asyncio.ensure_future(server.serve())` call in the addon's `load()` hook schedules uvicorn as a coroutine on mitmproxy's loop without blocking. Everything else — proxy traffic, API routes, SSE — is multiplexed on that one loop.

## Literal dev-mode command

`api/justfile:18`:

```
uv run mitmdump --mode reverse:https://api.anthropic.com --listen-port 8787 -s src/transport_matters/addon.py
```

Three flags do all the work:

- `--mode reverse:https://api.anthropic.com` — reverse-proxy mode, upstream pinned
- `--listen-port 8787` — client-facing port
- `-s src/transport_matters/addon.py` — loads the addon

## The asyncio loop sharing trick — `addon.py:338-346`

```python
app = create_app()
config = uvicorn.Config(app, host=\"127.0.0.1\", port=settings.web_port, log_config=None)
server = uvicorn.Server(config)
asyncio.ensure_future(server.serve())   # schedule on current loop, don't await
```

Why this works:

- `ensure_future` schedules a Task on the **already-running** (mitmproxy's) loop and returns instantly — zero block
- `server.serve()` is a long-lived coroutine that yields at every I/O boundary
- While it's yielded, the loop runs addon hooks for proxy flows
- While those yield (e.g. `await _run_pipeline`), the loop runs uvicorn's event handlers
- Single loop, no threads, no locks needed between the two halves

Shutdown caveat: there's no explicit uvicorn cleanup on mitmproxy shutdown. mitmproxy's `SIGINT` stops the loop, cancelling all tasks including `server.serve()`. The addon's `done()` hook calls `bp.clear_all()` so any paused breakpoints get released. Good enough but worth testing under \"Ctrl+C mid-pause.\"

## Addon lifecycle (`api/src/transport_matters/addon.py`)

| Hook | Sync/Async | What it does |
|---|---|---|
| `load(loader)` | sync | Init storage, create FastAPI app, schedule uvicorn on the loop. Called once. |
| `request(flow)` | async | Filter on `/v1/messages`, `_parse_request_ir → _run_pipeline → (optional) _handle_breakpoint → rewrite`. The breakpoint path `await`s an `asyncio.Event` that the FastAPI `/api/breakpoint/release` handler fires. |
| `response(flow)` | async | `_parse_response_ir → _build_req_stats → _build_pipeline_stats → _persist_exchange → _emit_exchange` (SSE). |
| `done()` | sync | `bp.clear_all()`. Releases awaiting flows so the loop can shut down cleanly. |

No `configure()` or `running()` hook today, and the agent confirms they're not needed.

## Why no cert install

Reverse proxy mode means the **client sends plain HTTP to `localhost:8787`**. mitmproxy terminates that plain connection, opens a fresh HTTPS connection to `api.anthropic.com` on the upstream side, and validates that cert normally. The client never sees a forged cert because the client-facing side isn't TLS at all.

Caveat: anything doing cert pinning or signed-request schemes breaks this. Anthropic's API uses a bearer token in the header (not signature-based), so it passes through cleanly.

## Concurrency — everything is single-loop

Two `asyncio.Lock`s only, both in storage:

- `DiskStorageBackend._index_lock` — protects `index.jsonl` append
- `DiskStorageBackend._rules_lock` — protects `rules.json` RMW (the fix from ALP-1740)

The breakpoint state dict `_paused` has **no lock**, intentionally. It's touched from `addon.request()` (mitmproxy hook) and from `/api/breakpoint/*` routes (FastAPI handlers). Both run on the same event loop, and neither holds state across an `await`, so there's no race window. This is a genuinely clean design — only works because the loop-sharing trick collapses two \"services\" into one execution context.

## Frontend ↔ addon coupling

All API calls in `www/src/api.ts` are **relative paths** (`/api/exchanges`, `/api/stream`, etc.). Vite dev proxy forwards to `localhost:8788` in dev; in packaged mode the React app is served by FastAPI on the same origin, so no CORS headers needed. The hardcoded `allow_origins=[\"http://localhost:3000\", \"http://localhost:5173\"]` at `main.py:74` is dev-only cruft — harmless in packaged mode but worth cleaning up.

## mitmproxy dependency surface

- `pyproject.toml:13`: `mitmproxy>=12.0` (loose)
- `uv.lock`: actual version **12.2.1**
- API usage is tiny: `http.HTTPFlow` type, `flow.request.get_text/set_text`, `flow.metadata`, `flow.response = MitmResponse.make(...)`, and the module-level addon export
- **Recommendation**: tighten to `mitmproxy>=12.2,<13` at release time. A major-version bump to 13.x could break addon hook signatures or flow.metadata — we want to opt in consciously.

## What this means for the CLI — decisions clarified

Earlier I waffled between \"shell out to mitmdump\" and \"embed DumpMaster programmatically.\" **Shell out wins**, for three concrete reasons the agent surfaced:

1. **Minimal coupling to mitmproxy internals.** The only API we touch is the documented addon hook contract plus the `mitmdump` command line. DumpMaster is a class from `mitmproxy.tools.dump` — calling it directly couples us to an internal-ish interface that moves between versions.
2. **The addon path inside an installed wheel is easy to resolve**:

   ```python
   from importlib.resources import files
   addon_path = files(\"transport_matters\") / \"addon.py\"
   ```

   This works whether `transport-matters` is installed as a wheel, an editable install, or a zipapp. Clean.
3. **Signals and debugging just work** — Ctrl+C hits `mitmdump`, mitmdump handles it, parent `transport-matters` process exits with mitmdump's exit code. If anything weirds out, the user can literally copy the `mitmdump ...` command out of `transport-matters claude --print-command` and run it themselves.

### What `transport-matters claude` actually has to do

```python
# pseudocode
def start(proxy_port=8787, web_port=8788, upstream=\"https://api.anthropic.com\",
          storage_dir=\"~/.transport-matters\", debug=False):
    addon_path = files(\"transport_matters\") / \"addon.py\"
    env = {**os.environ,
           \"WEB_PORT\": str(web_port),
           \"STORAGE_DIR\": str(storage_dir),
           \"DEBUG\": \"true\" if debug else \"false\"}
    cmd = [sys.executable, \"-m\", \"mitmproxy.tools.dump\",
           \"--mode\", f\"reverse:{upstream}\",
           \"--listen-port\", str(proxy_port),
           \"-s\", str(addon_path)]
    os.execvpe(cmd[0], cmd, env)  # or subprocess.run; execvpe means we disappear
```

A couple of refinements worth making:

- **`os.execvpe` over `subprocess.run`** so `transport-matters` doesn't sit as a parent wrapper eating its own process slot. Ctrl+C goes straight to mitmdump, PID is mitmdump's, process list is cleaner.
- **`--print-command`** as a debug flag so users can extract the raw command (for bug reports, for piping to their own systemd unit, for testing).
- **Exposing `--upstream`** from day one even though V1 only ships the Anthropic adapter. It's free, it future-proofs the CLI for Codex/custom upstreams, and it gives testers a way to point at a local mock server.

### Two gaps that are CLI-shaped, not code-shaped

1. **`settings.proxy_port` exists in `config.py` but is never read**, because the justfile hardcodes `--listen-port 8787`. The CLI needs to actually pass it through.
2. **The upstream URL is hardcoded in the justfile**, not in `config.py`. It needs to become a setting or a CLI flag. Probably both — CLI flag overrides env var overrides default.

## Risks the agent flagged that I'd flag back to you

1. **Ctrl+C mid-pause cleanup is untested.** The `done()` hook does call `bp.clear_all()`, but what happens to a client whose request is held in `await event.wait()` at shutdown? I'd want a test for this before declaring v1 done.
2. **No auth on the web UI.** Fine because `main.py` binds to `127.0.0.1`, but `SECRET_KEY` sits in `config.py` with a \"change-me-in-production\" default, suggesting a half-built intention. Either wire it up or remove the dead setting to avoid confusing future readers.
3. **The loose `mitmproxy>=12.0` constraint** is a ticking bomb for the packaged release. Tighten before PyPI upload.

## Proposed next step

Given this map, my earlier four-commit plan still holds, but I can be more concrete about commit C:

- **Commit C — the CLI entry point**, ~80 lines, new file `api/src/transport_matters/cli.py`. Uses `typer` (adds ~500KB of deps but gives us `--help`, subcommands, shell completion, type-safe options for free) or argparse if you want zero new deps. Exposes:
  - `transport-matters claude` — the main Claude command, `exec`s mitmdump with addon loaded
  - `transport-matters claude --print-command` — debug helper
  - `transport-matters claude --proxy-port / --web-port / --upstream / --storage-dir / --debug`
  - `transport-matters version` — prints `__version__` from the wheel
  - (Future) `transport-matters certs` — sanity-check mitmproxy cert dir, not needed in v1 because reverse proxy mode sidesteps certs

  Then `[project.scripts] transport-matters = \"transport_matters.cli:main\"` in `pyproject.toml`.

Want me to write Commit A (the `ci.yml` fix) first so main goes green today, then move to B + C + D in order? Or would you rather I sequence differently?
