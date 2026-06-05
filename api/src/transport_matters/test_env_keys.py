"""Pin the externally observable ``TRANSPORT_MATTERS_*`` wire names.

These strings are a cross-process and cross-language contract (the desktop app and
docs depend on the exact spelling), so a change here must be deliberate. Renaming
the prefix for the monorepo move updates this test on purpose.
"""

from transport_matters import env_keys


def test_prefix() -> None:
    assert env_keys.ENV_PREFIX == "TRANSPORT_MATTERS_"


def test_keys_match_wire_names() -> None:
    assert env_keys.PROXY_PORT == "TRANSPORT_MATTERS_PROXY_PORT"
    assert env_keys.WEB_PORT == "TRANSPORT_MATTERS_WEB_PORT"
    assert env_keys.UPSTREAM_URL == "TRANSPORT_MATTERS_UPSTREAM_URL"
    assert env_keys.STORAGE_DIR == "TRANSPORT_MATTERS_STORAGE_DIR"
    assert env_keys.RUN_ID == "TRANSPORT_MATTERS_RUN_ID"
    assert env_keys.CWD == "TRANSPORT_MATTERS_CWD"
    assert env_keys.CLI == "TRANSPORT_MATTERS_CLI"
    assert env_keys.CODEX_NATIVE_SESSION_ID == "TRANSPORT_MATTERS_CODEX_NATIVE_SESSION_ID"
    assert env_keys.CODEX_SOURCE_DESCRIPTOR == "TRANSPORT_MATTERS_CODEX_SOURCE_DESCRIPTOR"
