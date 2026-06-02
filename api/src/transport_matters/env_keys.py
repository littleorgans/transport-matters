"""Canonical names for the ``TRANSPORT_MATTERS_*`` process-environment contract.

Single source for the env-var prefix and every project-owned key, shared by the
writer (:mod:`transport_matters.cli.launch_runtime`) and the readers
(:class:`transport_matters.config.Settings` via ``env_prefix``,
:mod:`transport_matters.cli.paths`, and the Typer ``envvar=`` options). Deriving
each key from :data:`ENV_PREFIX` keeps the writer and readers on one symbol and
makes the littleorgans monorepo rename a one-line change.

Display copy (help text, banners, docstrings, error messages) intentionally keeps
literals for readability; grep the prefix when renaming. See
``NOTES/env-vars-transport-prefix.md``.
"""

ENV_PREFIX = "TRANSPORT_MATTERS_"

PROXY_PORT = f"{ENV_PREFIX}PROXY_PORT"
WEB_PORT = f"{ENV_PREFIX}WEB_PORT"
UPSTREAM_URL = f"{ENV_PREFIX}UPSTREAM_URL"
STORAGE_DIR = f"{ENV_PREFIX}STORAGE_DIR"
RUN_ID = f"{ENV_PREFIX}RUN_ID"
CWD = f"{ENV_PREFIX}CWD"
