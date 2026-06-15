"""Shared managed home constants."""

from __future__ import annotations

import re

from transport_matters.launch_environment import CLIENT_NAME_CLAUDE, CLIENT_NAME_CODEX

_CLAUDE_CONFIG_ENV = "CLAUDE_CONFIG_DIR"
_CODEX_HOME_ENV = "CODEX_HOME"
_CLAUDE_CONFIG_FILENAME = ".claude.json"
_CLAUDE_SETTINGS_FILENAME = "settings.json"
_CLAUDE_CREDENTIAL_FILENAME = ".credentials.json"
_CLAUDE_SKIP_DANGEROUS_KEY = "skipDangerousModePermissionPrompt"
_CODEX_AUTH_FILENAME = "auth.json"
_CODEX_CONFIG_FILENAME = "config.toml"
_CODEX_HOOK_TRUST_SOURCE_ENV = "TRANSPORT_MATTERS_CODEX_HOOK_TRUST_SOURCE_HOME"
_TRUSTED = "trusted"
_TRUST_LEVEL_LINE = 'trust_level = "trusted"'
_TRUST_LEVEL_RE = re.compile(r"^\s*trust_level\s*=")
_TOML_TABLE_RE = re.compile(r"^\s*\[")
# Codex keys ``[hooks.state."<abs hooks-file path>:<event>:<i>:<j>"]`` trust by the absolute
# path of the hooks file under ``CODEX_HOME``. The capture matches the quoted TOML basic-string
# key with escaped quote and backslash honoured so the overlay can repoint its source-home prefix.
_CODEX_HOOKS_STATE_HEADER_RE = re.compile(r'(?m)^\[hooks\.state\."(?P<key>(?:[^"\\]|\\.)*)"\]')
_JSON_FILE_MODE = 0o600
_DIRECTORY_MODE = 0o700
_CLAUDE_ROUTE_ENV_KEY = "ANTHROPIC_BASE_URL"
_NO_PROXY_ENV_KEY = "NO_PROXY"
# Claude daemon control plus dispatch state that must stay LOCAL to the overlay, never
# symlinked back to the source. The original route-loss bug is the daemon rebuilding a
# background worker's env from its dispatch state, so ``jobs/`` is route sensitive too.
_CLAUDE_DAEMON_LOCAL_NAMES = frozenset(
    {
        "daemon",
        "daemon.lock",
        "daemon.log",
        "daemon.status.json",
        "jobs",
    }
)
# Overlay-owned real files, also never symlinked from the content source.
_CLAUDE_OVERLAY_COPIED_NAMES = frozenset(
    {
        _CLAUDE_CONFIG_FILENAME,
        _CLAUDE_SETTINGS_FILENAME,
    }
)
_CLAUDE_OVERLAY_CREDENTIAL_NAMES = frozenset({_CLAUDE_CREDENTIAL_FILENAME})
_CLAUDE_OVERLAY_LOCAL_NAMES = (
    _CLAUDE_OVERLAY_COPIED_NAMES | _CLAUDE_DAEMON_LOCAL_NAMES | _CLAUDE_OVERLAY_CREDENTIAL_NAMES
)
_CODEX_OVERLAY_COPIED_NAMES = frozenset({_CODEX_CONFIG_FILENAME})
_CODEX_OVERLAY_CREDENTIAL_NAMES = frozenset({_CODEX_AUTH_FILENAME})
_CODEX_OVERLAY_LOCAL_NAMES = _CODEX_OVERLAY_COPIED_NAMES | _CODEX_OVERLAY_CREDENTIAL_NAMES
_OVERLAY_CREDENTIAL_NAMES_BY_CLIENT = {
    CLIENT_NAME_CLAUDE: _CLAUDE_OVERLAY_CREDENTIAL_NAMES,
    CLIENT_NAME_CODEX: _CODEX_OVERLAY_CREDENTIAL_NAMES,
}
# Entries never symlinked into any overlay, regardless of client. A source home that is
# or contains a git repo must not leak its ``.git`` into the per-run overlay.
_OVERLAY_NEVER_SYMLINK_NAMES = frozenset({".git"})
