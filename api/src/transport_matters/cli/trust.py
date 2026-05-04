"""Process scoped trust bootstrap for the Codex launch path."""

from __future__ import annotations

import ssl
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "ConfiguredCACertificateMissingError",
    "MitmproxyCAMissingError",
    "SystemTrustSnapshotError",
    "TrustBundleWriteError",
    "mitmproxy_ca_cert_path",
    "resolve_codex_ca_certificate",
]


class ConfiguredCACertificateMissingError(RuntimeError):
    """Raised when the caller supplied ``CODEX_CA_CERTIFICATE`` is unusable."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"configured CODEX_CA_CERTIFICATE does not exist: {path}")


class MitmproxyCAMissingError(RuntimeError):
    """Raised when mitmproxy's public CA certificate has not been generated."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"mitmproxy public CA not found: {path}")


class SystemTrustSnapshotError(RuntimeError):
    """Raised when Python's active trust roots cannot be serialized."""


class TrustBundleWriteError(RuntimeError):
    """Raised when the merged CA bundle cannot be written to disk."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"could not write merged CA bundle at {path}: {reason}")


def mitmproxy_ca_cert_path() -> Path:
    """Return mitmproxy's public CA certificate path for client trust."""
    return Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem"


def _system_trust_roots_as_pem() -> list[str]:
    """Serialize the interpreter's active trust roots as PEM blocks."""
    try:
        roots = ssl.create_default_context().get_ca_certs(binary_form=True)
    except Exception as exc:
        raise SystemTrustSnapshotError(
            "Python could not load the active default trust roots"
        ) from exc

    if not roots:
        raise SystemTrustSnapshotError(
            "Python reported zero active default trust roots"
        )

    serialized: list[str] = []
    seen: set[str] = set()
    for der_bytes in roots:
        try:
            pem = ssl.DER_cert_to_PEM_cert(der_bytes)
        except Exception as exc:
            raise SystemTrustSnapshotError(
                "Python could not serialize an active trust root to PEM"
            ) from exc
        if pem in seen:
            continue
        seen.add(pem)
        serialized.append(pem if pem.endswith("\n") else f"{pem}\n")
    return serialized


def _build_codex_ca_bundle(bundle_dir: Path) -> Path:
    """Merge system trust roots with the mitmproxy public CA."""
    mitmproxy_ca = mitmproxy_ca_cert_path()
    if not mitmproxy_ca.is_file():
        raise MitmproxyCAMissingError(mitmproxy_ca)

    try:
        bundle_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise TrustBundleWriteError(
            bundle_dir / "codex-ca-bundle.pem",
            str(exc),
        ) from exc

    bundle_path = bundle_dir / "codex-ca-bundle.pem"
    try:
        mitmproxy_pem = mitmproxy_ca.read_text(encoding="utf-8")
        if not mitmproxy_pem.endswith("\n"):
            mitmproxy_pem = f"{mitmproxy_pem}\n"

        with bundle_path.open("w", encoding="ascii") as handle:
            handle.writelines(_system_trust_roots_as_pem())
            handle.write(mitmproxy_pem)
    except OSError as exc:
        raise TrustBundleWriteError(bundle_path, str(exc)) from exc
    return bundle_path


def resolve_codex_ca_certificate(
    *,
    env: Mapping[str, str],
    bundle_dir: Path | None,
) -> Path:
    """Return the CA bundle path Codex should trust for this launch."""
    configured = env.get("CODEX_CA_CERTIFICATE")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_file():
            raise ConfiguredCACertificateMissingError(path)
        return path.resolve()
    if bundle_dir is None:
        raise ValueError("bundle_dir is required when CODEX_CA_CERTIFICATE is unset")
    return _build_codex_ca_bundle(bundle_dir)
