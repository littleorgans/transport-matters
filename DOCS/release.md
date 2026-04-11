# The Release

## What's really in front of us

The current `.github/workflows/ci.yml` was scaffolded from a Python-library template. It tests nothing about what Manicure actually *is*:

- **www/ isn't built, tested, linted, or even checked out** in CI. The entire React side is invisible to the pipeline.
- The `pytest tests/ --cov=app` line isn't a bug — it's a relic from before the package was named `manicure` and before unit tests were colocated under `src/`.
- There's no release job, no artifact build, no version tagging.
- The 80% coverage gate is aspirational, not grounded (we're actually at 83.54% locally — the gate *would* pass if CI could see the tests).

So \"fix the workflow\" is the wrong frame. The right frame is: **what does v1 release look like, and what does CI need to enforce to make that release trustworthy?**

## The real questions

Before I write any YAML, I need you to pick on five things. Each one has a fork that changes the shape of CI.

### 1. How do users actually install Manicure?

Three options, wildly different implications:

| Option | Release artifact | CI's job |
|---|---|---|
| **PyPI** (`uvx manicure` / `pipx install manicure`) | A wheel that embeds the built www/ static assets | Build www, copy into package, build wheel, publish to PyPI, verify install in a clean env |
| **GitHub release + curl-install script** (`curl … \\| bash`) | Tagged release with wheel or tarball attached | Same as PyPI but publish goes to GH Releases instead of PyPI |
| **Homebrew tap / formula** | PyPI wheel + formula update | PyPI path plus a formula-bump step |

My read: **PyPI is the right v1 target**. `uvx manicure` is one command and it's how Stuart already ships things. Homebrew is a v1.1 nice-to-have. Curl-install is a v0 hack that we should skip.

Do you agree, or do you want curl-install as the primary path?

### 2. Where does the built www/ live?

Two clean choices:

- **Embed inside the Python wheel** — `pnpm build` runs at release time, output lands in `api/src/manicure/_www/`, the FastAPI server mounts it as `StaticFiles`. One artifact, one install, no network at first run. Matches how mitmproxy itself ships.
- **Download at first run** — smaller wheel, but `manicure` now needs network to boot, versioning gets weird, and it adds a supply-chain surface.

Embed is the obvious call unless you have a reason I don't see.

### 3. What does \"green\" mean on a PR?

A minimal-but-honest v1 gate:

**Backend (`api/`):**

- `ruff check` + `ruff format --check`
- `mypy --strict`
- `pytest` (no path override — let `testpaths = [\"src\", \"tests\"]` do its job)
- Coverage: **drop `fail_under = 80`**, report as a signal not a gate. Let it ratchet up from a real baseline. 80% was a template number.

**Frontend (`www/`):**

- `pnpm install --frozen-lockfile`
- `pnpm biome check src`
- `pnpm tsc -b --noEmit`
- `pnpm test --run` (vitest)
- **`pnpm build`** — this catches the \"works in dev, breaks in prod bundle\" class of bug. Currently uncovered.

**Integration smoke (optional but cheap):**

- After building www/, install the Python wheel in a throwaway venv and run `manicure --help` (or equivalent boot check) to prove the wheel isn't broken.

### 4. What triggers a release?

Three models:

- **Tag-triggered**: push `v1.0.0` → CI builds wheel → publishes to PyPI + GH Release. Standard, simple, works with `git tag`.
- **Manual dispatch**: GitHub Actions \"Run workflow\" button. Good for paranoid first release.
- **Merge to `release` branch**: heavier, only worth it if you end up with hotfix branches.

For v1 I'd start with **manual dispatch** (so the first few releases are explicit), then switch to **tag-triggered** once you trust the pipeline.

### 5. Platform + Python matrix

- **Linux + macOS** on Python **3.12 + 3.13** for the test matrix. That's four jobs, all cheap.
- Skip Windows for v1 unless someone asks. mitmproxy works on Windows but it's a second-class platform and every Windows-only breakage is an interrupt.
- Node on the www/ side: pin via `packageManager` in package.json, use `actions/setup-node@v4` with that pin.

## What I'd propose, concretely

Two workflows, not one:

```
.github/workflows/
├── ci.yml       # runs on every push / PR — gates merges
└── release.yml  # runs on workflow_dispatch (v1) or tag (later)
```

**`ci.yml` jobs:**

1. `backend-lint` (ruff + mypy, Ubuntu only)
2. `backend-test` (pytest matrix: {ubuntu, macos} × {3.12, 3.13})
3. `frontend-lint` (biome + tsc)
4. `frontend-test` (vitest)
5. `frontend-build` (`pnpm build` — artifact-producing sanity check)
6. `integration-smoke` *(optional)*: build www, build wheel, install wheel in clean venv, boot check

**`release.yml` jobs:**

1. Re-run the full `ci.yml` gate (or depend on the latest green `ci.yml` for the same SHA)
2. `pnpm build` → copy `www/dist/` into `api/src/manicure/_www/`
3. `uv build` (wheel + sdist)
4. Sanity install in a clean venv, run `manicure --version`, grep the www assets are inside the wheel with `unzip -l dist/*.whl`
5. Publish to PyPI via **trusted publishing (OIDC)** — no API tokens, no secrets
6. Attach artifacts to a GitHub Release

## The open questions I need answered before I can write this

1. **PyPI package name + ownership**: Is `manicure` available on PyPI? Do you have an account with trusted publishing set up, or do we need to reserve the name first? (Name squatting happens fast.)
2. **Entry point**: What's the CLI entry point — is `api/pyproject.toml` already set up with `[project.scripts] manicure = \"manicure.__main__:main\"`, or do we need to add it?
3. **www/ embed path**: Am I right that the FastAPI server should serve `api/src/manicure/_www/` as static files? That changes how `main.py` is wired — currently it probably looks for a dev server URL. Need to check.
4. **Version source of truth**: Is the version pinned in `api/pyproject.toml`, or do you want to tag-derive it (setuptools-scm / hatch-vcs)?
5. **Curl-install or PyPI-first?** (Question #1 above.)
6. **The 80% coverage gate**: kill it, or keep it at 83% (current real number) and let it only go up?

Tell me which of these you already have opinions on and I'll investigate the rest in the repo before writing anything. Once we've agreed on shape I'll build `ci.yml` + `release.yml` as a unit, not patch the existing file.
