"""Tests for the Codex trust bootstrap helper."""

from __future__ import annotations

import ssl
from typing import TYPE_CHECKING

import pytest

from transport_matters.cli import trust
from transport_matters.cli.trust import (
    ConfiguredCACertificateMissingError,
    MitmproxyCAMissingError,
    SystemTrustSnapshotError,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_resolve_codex_ca_certificate_uses_configured_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "configured.pem"
    bundle.write_text("configured", encoding="utf-8")

    resolved = trust.resolve_codex_ca_certificate(
        env={"CODEX_CA_CERTIFICATE": str(bundle)},
        bundle_dir=None,
    )

    assert resolved == bundle.resolve()


def test_resolve_codex_ca_certificate_rejects_missing_configured_bundle() -> None:
    with pytest.raises(ConfiguredCACertificateMissingError):
        trust.resolve_codex_ca_certificate(
            env={"CODEX_CA_CERTIFICATE": "/missing/bundle.pem"},
            bundle_dir=None,
        )


def test_resolve_codex_ca_certificate_merges_system_roots_and_mitmproxy_ca(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    mitmproxy_dir = tmp_path / ".mitmproxy"
    mitmproxy_dir.mkdir()
    (mitmproxy_dir / "mitmproxy-ca-cert.pem").write_text(
        "-----BEGIN CERTIFICATE-----\nMITM\n-----END CERTIFICATE-----\n",
        encoding="utf-8",
    )

    class FakeContext:
        def get_ca_certs(self, *, binary_form: bool) -> list[bytes]:
            assert binary_form is True
            return [b"root-a", b"root-a", b"root-b"]

    monkeypatch.setattr(
        "transport_matters.cli.trust.ssl.create_default_context",
        lambda: FakeContext(),
    )
    monkeypatch.setattr(
        "transport_matters.cli.trust.ssl.DER_cert_to_PEM_cert",
        lambda der_bytes: (
            f"-----BEGIN CERTIFICATE-----\n{der_bytes.decode()}\n-----END CERTIFICATE-----\n"
        ),
    )

    bundle = trust.resolve_codex_ca_certificate(env={}, bundle_dir=tmp_path / "bundle")
    text = bundle.read_text(encoding="ascii")

    assert text.count("root-a") == 1
    assert text.count("root-b") == 1
    assert "MITM" in text


def test_resolve_codex_ca_certificate_requires_mitmproxy_ca(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(MitmproxyCAMissingError):
        trust.resolve_codex_ca_certificate(env={}, bundle_dir=tmp_path / "bundle")


def test_resolve_codex_ca_certificate_reports_system_snapshot_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    mitmproxy_dir = tmp_path / ".mitmproxy"
    mitmproxy_dir.mkdir()
    (mitmproxy_dir / "mitmproxy-ca-cert.pem").write_text(
        "-----BEGIN CERTIFICATE-----\nMITM\n-----END CERTIFICATE-----\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "transport_matters.cli.trust.ssl.create_default_context",
        lambda: (_ for _ in ()).throw(ssl.SSLError("broken ssl")),
    )

    with pytest.raises(SystemTrustSnapshotError):
        trust.resolve_codex_ca_certificate(env={}, bundle_dir=tmp_path / "bundle")
