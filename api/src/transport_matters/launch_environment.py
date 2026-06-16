"""Neutral environment assembly for Transport Matters managed launches."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from transport_matters import env_keys
from transport_matters.capabilities import CLI_NAME_CLAUDE, CLI_NAME_CODEX

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

__all__ = [
    "CLIENT_NAME_CLAUDE",
    "CLIENT_NAME_CODEX",
    "HOME_DIR_ENV_BY_CLIENT",
    "LOOPBACK_NO_PROXY",
    "build_launch_env",
    "build_managed_child_env",
    "managed_child_shell_env_excludes",
]

CLIENT_NAME_CLAUDE: str = CLI_NAME_CLAUDE
CLIENT_NAME_CODEX: str = CLI_NAME_CODEX

_MANAGED_CHILD_PROXY_ENV_KEYS = frozenset(
    {
        "ALL_PROXY",
        "all_proxy",
        "BUNDLE_HTTP_PROXY",
        "BUNDLE_HTTPS_PROXY",
        "BUNDLE_NO_PROXY",
        "DOCKER_HTTP_PROXY",
        "DOCKER_HTTPS_PROXY",
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "NO_PROXY",
        "no_proxy",
        "FTP_PROXY",
        "ftp_proxy",
        "WS_PROXY",
        "ws_proxy",
        "WSS_PROXY",
        "wss_proxy",
        "npm_config_proxy",
        "NPM_CONFIG_PROXY",
        "npm_config_http_proxy",
        "NPM_CONFIG_HTTP_PROXY",
        "npm_config_https_proxy",
        "NPM_CONFIG_HTTPS_PROXY",
        "npm_config_noproxy",
        "NPM_CONFIG_NOPROXY",
        "npm_config_no_proxy",
        "NPM_CONFIG_NO_PROXY",
        "PIP_PROXY",
        "YARN_HTTP_PROXY",
        "YARN_HTTPS_PROXY",
        "YARN_NO_PROXY",
    }
)

_MANAGED_CHILD_PROXY_INTERNAL_ENV_KEYS = frozenset(
    {
        "CODEX_NETWORK_ALLOW_LOCAL_BINDING",
        "CODEX_NETWORK_PROXY_ACTIVE",
        "ELECTRON_GET_USE_PROXY",
    }
)

_MANAGED_CHILD_TRUST_ENV_KEYS = frozenset(
    {
        "CODEX_CA_CERTIFICATE",
        "CURL_CA_BUNDLE",
        "NODE_EXTRA_CA_CERTS",
        "NODE_TLS_REJECT_UNAUTHORIZED",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "npm_config_cafile",
        "NPM_CONFIG_CAFILE",
    }
)

_MANAGED_CHILD_TRANSPORT_INTERNAL_ENV_KEYS = frozenset({env_keys.LAUNCH_FIELDS})
_MANAGED_CHILD_SHELL_INTERNAL_ENV_KEYS = frozenset({env_keys.RESUME_CONTEXT})

LOOPBACK_NO_PROXY = "127.0.0.1,localhost"

HOME_DIR_ENV_BY_CLIENT: dict[str, str] = {
    CLIENT_NAME_CLAUDE: "CLAUDE_CONFIG_DIR",
    CLIENT_NAME_CODEX: "CODEX_HOME",
}


def managed_child_shell_env_excludes() -> tuple[str, ...]:
    """Return managed env keys that nested tool shells should not inherit."""
    return tuple(
        sorted(
            _MANAGED_CHILD_PROXY_ENV_KEYS
            | _MANAGED_CHILD_TRUST_ENV_KEYS
            | _MANAGED_CHILD_TRANSPORT_INTERNAL_ENV_KEYS
            | _MANAGED_CHILD_SHELL_INTERNAL_ENV_KEYS
        )
    )


def build_launch_env(
    *,
    working_dir: Path,
    storage_dir: Path,
    proxy_port: int,
    web_port: int | None,
    run_id: str,
    web_runtime: str = "embedded",
    cli: str | None = None,
    home_dir: Path | None = None,
    owned_native_session_id: str | None = None,
    owned_source_descriptor: str | None = None,
    launch_fields: Mapping[str, object] | None = None,
    default_client_passthrough: Sequence[str] = (),
) -> dict[str, str]:
    """Return the shared runtime environment for a launch attempt.

    ``cli`` and the ``owned_*`` values are the managed mint contract: a mint capable
    launcher hands the addon the harness cli plus the native id and source descriptor
    of the transcript it owns, so the addon can stamp them onto the session row before
    cursor registration.

    ``home_dir`` is the managed ``--agent-home-dir``. The child gets the home via
    ``CLAUDE_CONFIG_DIR`` or ``CODEX_HOME`` in :func:`build_managed_child_env`; the
    addon gets it through ``TRANSPORT_MATTERS_AGENT_HOME_DIR`` so adapter binding and
    locate resolve transcripts under the same managed home.
    """
    env = os.environ.copy()
    env[env_keys.STORAGE_DIR] = str(storage_dir)
    if web_port is not None:
        env[env_keys.WEB_PORT] = str(web_port)
    env[env_keys.WEB_RUNTIME] = web_runtime
    env[env_keys.PROXY_PORT] = str(proxy_port)
    env[env_keys.RUN_ID] = run_id
    env[env_keys.CWD] = str(working_dir)
    if cli is not None:
        env[env_keys.CLI] = cli
    if home_dir is not None:
        env[env_keys.AGENT_HOME_DIR] = str(home_dir)
    if default_client_passthrough:
        env[env_keys.DEFAULT_CLIENT_PASSTHROUGH] = json.dumps(
            list(default_client_passthrough),
            separators=(",", ":"),
        )
    if owned_native_session_id is not None:
        env[env_keys.OWNED_NATIVE_SESSION_ID] = owned_native_session_id
    if owned_source_descriptor is not None:
        env[env_keys.OWNED_SOURCE_DESCRIPTOR] = owned_source_descriptor
    if launch_fields:
        env[env_keys.LAUNCH_FIELDS] = json.dumps(
            dict(launch_fields),
            separators=(",", ":"),
        )
        resume_context = launch_fields.get("resume_context")
        if resume_context is not None:
            env[env_keys.RESUME_CONTEXT] = json.dumps(
                resume_context,
                separators=(",", ":"),
            )
        else:
            env.pop(env_keys.RESUME_CONTEXT, None)
    else:
        env.pop(env_keys.LAUNCH_FIELDS, None)
        env.pop(env_keys.RESUME_CONTEXT, None)
    return env


def build_managed_child_env(
    base_env: Mapping[str, str],
    *,
    client_name: str | None = None,
    home_dir: Path | None = None,
    proxy_url: str | None = None,
    codex_ca_certificate: str | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a deterministic child env that cannot bypass proxy or trust."""
    env = dict(base_env)
    for key in (
        _MANAGED_CHILD_PROXY_ENV_KEYS
        | _MANAGED_CHILD_PROXY_INTERNAL_ENV_KEYS
        | _MANAGED_CHILD_TRUST_ENV_KEYS
        | _MANAGED_CHILD_TRANSPORT_INTERNAL_ENV_KEYS
    ):
        env.pop(key, None)

    if proxy_url is not None:
        # Codex uses this marker to strip managed proxy vars from user commands.
        env["CODEX_NETWORK_PROXY_ACTIVE"] = "1"
        env["HTTP_PROXY"] = proxy_url
        env["HTTPS_PROXY"] = proxy_url
        env["ALL_PROXY"] = proxy_url
        env["WS_PROXY"] = proxy_url
        env["WSS_PROXY"] = proxy_url
        env["http_proxy"] = proxy_url
        env["https_proxy"] = proxy_url
        env["all_proxy"] = proxy_url
        env["ws_proxy"] = proxy_url
        env["wss_proxy"] = proxy_url

    env["NO_PROXY"] = LOOPBACK_NO_PROXY
    env["no_proxy"] = LOOPBACK_NO_PROXY

    if codex_ca_certificate is not None:
        env["CODEX_CA_CERTIFICATE"] = codex_ca_certificate
    if home_dir is not None:
        if client_name is None:
            raise ValueError(f"unmapped managed client home dir: {client_name!r}")
        try:
            env_key = HOME_DIR_ENV_BY_CLIENT[client_name]
        except KeyError as exc:
            raise ValueError(f"unmapped managed client home dir: {client_name!r}") from exc
        env[env_key] = str(home_dir)
    if extra_env is not None:
        env.update(extra_env)
    return env
