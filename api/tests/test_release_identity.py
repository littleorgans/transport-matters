from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_SURFACES = [
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    "release.sh",
    "install.sh",
    "DOCS/release.md",
    "justfile",
    "api/justfile",
    "www/package.json",
    "www/vite.config.ts",
]


def read_surface(path: str) -> str:
    return (REPO_ROOT / path).read_text()


def test_release_surfaces_use_transport_matters_identity() -> None:
    combined = "\n".join(read_surface(path) for path in RELEASE_SURFACES)

    for old_identity in ("manicure", "Manicure", "MANICURE"):
        assert old_identity not in combined

    assert "transport-matters" in combined
    assert "TRANSPORT_MATTERS_VERSION" in combined
    assert "TRANSPORT_MATTERS_INSTALL_VERSION" in combined
    assert "TRANSPORT_MATTERS_SKIP_UV_INSTALL" in combined


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
