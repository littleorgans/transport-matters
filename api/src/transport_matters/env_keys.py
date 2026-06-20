"""Canonical names for the ``TRANSPORT_MATTERS_*`` process-environment contract.

Single source for the env-var prefix and every project-owned key, shared by the
writer (:mod:`transport_matters.launch_environment`) and the readers
(:class:`transport_matters.config.Settings` via ``env_prefix``,
:mod:`transport_matters.cli.paths`, and the Typer ``envvar=`` options). Deriving
each key from :data:`ENV_PREFIX` keeps the writer and readers on one symbol and
makes the littleorgans monorepo rename a one-line change.

Display copy (help text, banners, docstrings, error messages) intentionally keeps
literals for readability; grep the prefix when renaming. See
``NOTES/env-vars-transport-prefix.md``.
"""

ENV_PREFIX = "TRANSPORT_MATTERS_"

# Operator config/data root. Relocates the whole ``~/.transport-matters`` tree:
# ``settings.toml`` (operator config) is ALWAYS read from ``$TRANSPORT_MATTERS_HOME``,
# independent of the per-run STORAGE_DIR a launch sets into the child env. Default
# ``~/.transport-matters``. Distinct from ``AGENT_HOME_DIR`` (the managed agent home).
HOME = f"{ENV_PREFIX}HOME"
CHANNEL = f"{ENV_PREFIX}CHANNEL"

PROXY_PORT = f"{ENV_PREFIX}PROXY_PORT"
WEB_PORT = f"{ENV_PREFIX}WEB_PORT"
WEB_RUNTIME = f"{ENV_PREFIX}WEB_RUNTIME"
DEFAULT_CLIENT_PASSTHROUGH = f"{ENV_PREFIX}DEFAULT_CLIENT_PASSTHROUGH"
UPSTREAM_URL = f"{ENV_PREFIX}UPSTREAM_URL"
STORAGE_DIR = f"{ENV_PREFIX}STORAGE_DIR"
RUN_ID = f"{ENV_PREFIX}RUN_ID"
CWD = f"{ENV_PREFIX}CWD"
HARNESS = f"{ENV_PREFIX}HARNESS"
# Managed-mint (§5.2b/§5.2c): provider-neutral. The launcher owns the transcript a managed harness will
# write, so it hands the addon the native id it minted (== the wire-observed session id) and the JSON
# source_descriptor for that owned transcript. The addon stamps both onto the session row whose wire
# id matches, before cursor registration, so the tailer byte-tails the owned path instead of globbing.
# Set by every mint-capable launch (codex: rollout; claude: deterministic transcript path).
OWNED_NATIVE_SESSION_ID = f"{ENV_PREFIX}OWNED_NATIVE_SESSION_ID"
OWNED_SOURCE_DESCRIPTOR = f"{ENV_PREFIX}OWNED_SOURCE_DESCRIPTOR"
# Generic launcher supplied binding fields, JSON encoded. This keeps future launch metadata on one
# carrier instead of adding a new settings/env/model-copy path for every field.
LAUNCH_FIELDS = f"{ENV_PREFIX}LAUNCH_FIELDS"
# Thin B6 continuation context for the managed agent process, JSON encoded. It carries durable
# Postgres references and text snippets only, never local transcript paths.
RESUME_CONTEXT = f"{ENV_PREFIX}RESUME_CONTEXT"
# Managed ``--agent-home-dir`` for this launch (§11.1). The child gets the home via CLAUDE_CONFIG_DIR /
# CODEX_HOME (``build_managed_child_env``); the addon gets it HERE so adapter binding stamps it onto
# the binding and ``locate`` resolves the transcript root under the managed home (the manifest also
# carries it but is unlinked on exit, so it cannot be the addon's durable channel). Unset = native home.
AGENT_HOME_DIR = f"{ENV_PREFIX}AGENT_HOME_DIR"
DESKTOP_APP_BIN = f"{ENV_PREFIX}DESKTOP_APP_BIN"
DESKTOP_APP_DIR = f"{ENV_PREFIX}DESKTOP_APP_DIR"
DESKTOP_CLIENT = f"{ENV_PREFIX}DESKTOP_CLIENT"
DESKTOP_ELECTRON_BIN = f"{ENV_PREFIX}DESKTOP_ELECTRON_BIN"
DESKTOP_ROUTE_URL = f"{ENV_PREFIX}DESKTOP_ROUTE_URL"
DATABASE_URL = f"{ENV_PREFIX}DATABASE_URL"
TEST_DATABASE_URL = f"{ENV_PREFIX}TEST_DATABASE_URL"
DOCKER_PG_PORT = f"{ENV_PREFIX}DOCKER_PG_PORT"
