# Phase 2 Release Readiness Review

Review issue: `ALP-2353`

Branch baseline: `origin/main..HEAD` through `ALP-2350`

## Outcome

Phase 2 is not release ready yet. The post execution review found one active
rename leftover in local developer surfaces and captured it as corrective issue
`ALP-2355`.

Release tagging, PyPI publishing, desktop signing, desktop notarization, and
desktop artifact upload remain human owned actions.

## Target Group Results

### Rename Implementation, `ALP-2335` Through `ALP-2342`

Result: fail pending `ALP-2355`.

Package metadata, Python imports, frontend package identity, public CLI command,
runtime env prefix, backend storage roots, and frontend persisted keys have been
renamed directly to Transport Matters surfaces.

The residual scan still found active old identity in:

- `scripts/local-dev-mode.sh`, which still checks and launches the old
  executable name.
- `api/CLAUDE.md`, which still references old package paths in active developer
  guidance.

The remaining old identity matches outside `ALP-2355` are inert test prose,
negative assertions, local path fixture strings, or pre-existing non-rename
legacy behavior.

### Web Reuse, `ALP-2343` And `ALP-2344`

Result: pass.

`www/` remains the renderer source of truth. `BrowserAppShell` owns browser
transport, EventSource creation, API fetching, route hotkeys, and persisted UI
state. `RouteLayout` renders from props, with tests preventing browser transport
construction inside the shared layout boundary.

### Electron Boundary, `ALP-2345` Through `ALP-2348`

Result: pass.

`desktop/` owns the Electron main process, preload surface, backend launch,
hosted loopback loading, package smoke, and desktop lifecycle. It does not import
the React route tree. The BrowserWindow uses context isolation, sandbox, no node
integration, controlled loopback navigation, denied new windows, and a minimal
preload API.

### Verification And Release, `ALP-2349` Through `ALP-2354`

Result: fail pending `ALP-2355`.

Recorded evidence covers backend, frontend, browser, Electron, package, wheel,
installer, and release checks. Local wheel smoke installed
`dist/transport_matters-*.whl`, ran the `transport-matters` CLI command surface,
and verified `transport_matters/www/index.html` in the wheel. Electron package
smoke has local unsigned coverage only.

Release readiness remains blocked by the active local developer rename leftover
captured in `ALP-2355`.

## Compatibility And Migration Review

No Phase 2 worker added rename compatibility aliases, fallback env reads, old
storage root fallback, workspace migration, manifest migration, old diagnostic
probe reads, hidden CLI compatibility commands, PyPI publish, tag push, desktop
signing, notarization, or artifact upload.

Search results containing `legacy`, `migration`, `fallback`, or `alias` refer to
pre-existing Codex repair behavior, non-rename fallback logic, or tests that
assert removed old surfaces stay removed.

## Corrective Work

`ALP-2355` is the only corrective issue found by this review.

Release authorization should wait until `ALP-2355` is complete and its focused
residual scan plus `just check && just build && just test` pass.
