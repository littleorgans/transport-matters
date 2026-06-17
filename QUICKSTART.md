# Quickstart

Transport Matters proxies and indexes your coding-agent sessions into a session
store. That store is **Postgres**, so setup is three steps: install, point it at
a Postgres, run.

## 1. Install

```bash
curl -fsSL https://github.com/littleorgans/transport-matters/releases/latest/download/install.sh | bash
# or, if you already have uv:
uv tool install transport-matters
```

## 2. Provide a Postgres

Transport Matters does not provision Postgres for you (that is your DB to own).
Pick one:

**Local Docker (simplest).** A throwaway local Postgres matching the scaffolded
defaults:

```bash
docker run -d --name tm-postgres -p 127.0.0.1:55432:5432 \
  -e POSTGRES_USER=tm -e POSTGRES_PASSWORD=tm -e POSTGRES_DB=transport_matters \
  postgres:17
```

(From a source checkout you can use `docker compose up -d` instead.)

**Existing local or cloud/managed Postgres.** Create a database and use its
connection string in step 3.

## 3. Configure the connection

On first launch Transport Matters writes `~/.transport-matters/settings.toml`
from a packaged template, already pointing at the local-Docker default above
(`postgresql://tm:tm@localhost:55432/transport_matters`). Edit `[database] url`
there for a different DB, or override with an environment variable (env wins):

```bash
export TRANSPORT_MATTERS_DATABASE_URL=postgresql://user:pass@host:5432/dbname
```

The schema is applied automatically on launch (advisory-locked) — you never run
Alembic by hand. `transport-matters db status` shows the current vs target
revision; `transport-matters db upgrade` applies migrations explicitly.

## 4. Run

```bash
transport-matters desktop                  # desktop canvas + local backend
transport-matters claude --work-dir ~/project
transport-matters codex
```

If Postgres is unreachable, launch **stops with setup instructions** rather than
starting half-broken. `transport-matters doctor` checks your environment,
including session-store connectivity and schema.

## Environment

| Variable | Purpose |
| --- | --- |
| `TRANSPORT_MATTERS_DATABASE_URL` | Session-store Postgres connection (overrides `settings.toml`) |
| `TRANSPORT_MATTERS_HOME` | Root for config + storage (default `~/.transport-matters`) |
| `TRANSPORT_MATTERS_AGENT_HOME_DIR` | Override the launched agent's home dir |
| `TRANSPORT_MATTERS_PROXY_PORT` / `TRANSPORT_MATTERS_WEB_PORT` | Pin ports (default kernel-allocated) |
| `TRANSPORT_MATTERS_STORAGE_DIR` | Relocate per-run capture data |
