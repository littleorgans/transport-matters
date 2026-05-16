from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
OLD_IDENTITIES = ("manicure", "Manicure", "MANICURE")
RELEASE_SURFACES = [
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    "scripts/release.sh",
    "scripts/install.sh",
    "justfile",
    "api/justfile",
    "www/package.json",
    "www/vite.config.ts",
]
ACTIVE_BACKEND_SURFACES = [
    "api/.env.example",
    *[
        str(path.relative_to(REPO_ROOT))
        for path in sorted((REPO_ROOT / "api/src/transport_matters").rglob("*.py"))
        if not path.name.startswith("test_") and path.name != "conftest.py"
    ],
]
LOCAL_DEVELOPER_SURFACES = [
    "scripts/local-dev-mode.sh",
    "api/CLAUDE.md",
]
DOCS_IDENTITY_SURFACES = [
    "README.md",
    "api/README.md",
]


def read_surface(path: str) -> str:
    return (REPO_ROOT / path).read_text()


def test_release_surfaces_use_transport_matters_identity() -> None:
    combined = "\n".join(read_surface(path) for path in RELEASE_SURFACES)

    for old_identity in OLD_IDENTITIES:
        assert old_identity not in combined

    assert "transport-matters" in combined
    assert "TRANSPORT_MATTERS_VERSION" in combined
    assert "TRANSPORT_MATTERS_INSTALL_VERSION" in combined
    assert "TRANSPORT_MATTERS_SKIP_UV_INSTALL" in combined


def test_active_backend_surfaces_use_transport_matters_identity() -> None:
    combined = "\n".join(read_surface(path) for path in ACTIVE_BACKEND_SURFACES)

    old_identities = (
        "mani" + "cure",
        "Mani" + "cure",
        "MANI" + "CURE",
        "mani" + "cure_version",
        ".mani" + "cure-doctor-probe",
    )
    for old_identity in old_identities:
        assert old_identity not in combined

    assert "transport-matters" in combined
    assert "Transport Matters" in combined
    assert "TRANSPORT_MATTERS_" in combined


def test_local_developer_surfaces_use_transport_matters_identity() -> None:
    combined = "\n".join(read_surface(path) for path in LOCAL_DEVELOPER_SURFACES)

    for old_identity in OLD_IDENTITIES:
        assert old_identity not in combined

    assert "transport-matters" in combined
    assert "transport_matters" in combined


def test_active_docs_do_not_encode_old_brand_etymology() -> None:
    combined = "\n".join(read_surface(path) for path in DOCS_IDENTITY_SURFACES)

    for old_identity in (
        "**mani**",
        "**cur**",
        "manifest + curate",
        "manifest + curat",
    ):
        assert old_identity.lower() not in combined.lower()

    assert "Transport Matters" in combined
    assert "transport-matters" in combined


def test_ci_and_release_smoke_the_public_transport_matters_command() -> None:
    ci_workflow = read_surface(".github/workflows/ci.yml")
    release_workflow = read_surface(".github/workflows/release.yml")

    for workflow in (ci_workflow, release_workflow):
        assert "/tmp/smoke/bin/transport-matters --version" in workflow
        assert "/tmp/smoke/bin/transport-matters version" in workflow
        assert "/tmp/smoke/bin/transport-matters paths --json" in workflow
        assert "/tmp/smoke/bin/transport-matters --help > /dev/null" in workflow
        assert "/tmp/smoke/bin/transport-matters claude --help > /dev/null" in workflow
        assert "/tmp/smoke/bin/transport-matters doctor --help > /dev/null" in workflow


def test_release_artifacts_use_normalized_transport_matters_names() -> None:
    release_workflow = read_surface(".github/workflows/release.yml")
    ci_workflow = read_surface(".github/workflows/ci.yml")

    assert "dist/transport_matters-*.whl" in release_workflow
    assert "dist/transport_matters-*.tar.gz" in release_workflow
    assert "sha256sum transport_matters-* > SHA256SUMS" in release_workflow
    assert "--title \"Transport Matters $VERSION\"" in release_workflow
    assert "scripts/install.sh" in release_workflow
    assert "dist/transport_matters-*.whl" in ci_workflow


def test_release_surfaces_do_not_advertise_deferred_migration_work() -> None:
    combined = "\n".join(read_surface(path) for path in RELEASE_SURFACES)

    for deferred_term in (
        "manicure compatibility",
        "compatibility command",
        "alias command",
        "shorter transport-matters.sh alias",
        "storage migration",
        "workspace migration",
    ):
        assert deferred_term not in combined.lower()
