"""Codex CA bundle cache tests."""

import contextlib
from typing import TYPE_CHECKING

from transport_matters.cli.codex_cmd import (
    _reset_codex_ca_certificate_cache_for_tests,
    _resolve_codex_ca_certificate_or_exit,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_codex_ca_cache_re_resolves_when_env_basis_changes(tmp_path: Path) -> None:
    _reset_codex_ca_certificate_cache_for_tests()
    calls = 0

    def fake_resolve(*, env: dict[str, str], bundle_dir: Path | None) -> Path:
        nonlocal calls
        calls += 1
        assert bundle_dir is not None
        bundle_path = bundle_dir / "codex-ca-bundle.pem"
        bundle_path.write_text(f"generated {calls}", encoding="utf-8")
        return bundle_path

    env = {"HOME": str(tmp_path), "TM_TEST_INPUT": "one"}
    with contextlib.ExitStack() as stack:
        first = _resolve_codex_ca_certificate_or_exit(
            stack=stack,
            print_command=False,
            resolve_codex_ca_certificate=fake_resolve,
            env=env,
        )
    with contextlib.ExitStack() as stack:
        second = _resolve_codex_ca_certificate_or_exit(
            stack=stack,
            print_command=False,
            resolve_codex_ca_certificate=fake_resolve,
            env=env,
        )
    changed_env = env | {"TM_TEST_INPUT": "two"}
    with contextlib.ExitStack() as stack:
        third = _resolve_codex_ca_certificate_or_exit(
            stack=stack,
            print_command=False,
            resolve_codex_ca_certificate=fake_resolve,
            env=changed_env,
        )

    assert first == second
    assert third != first
    assert calls == 2
