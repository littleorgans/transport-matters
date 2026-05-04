import tomllib
from pathlib import Path


PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_python_distribution_metadata_uses_transport_matters() -> None:
    pyproject = tomllib.loads(PYPROJECT.read_text())

    project = pyproject["project"]
    assert project["name"] == "transport-matters"
    assert project["urls"] == {
        "Homepage": "https://github.com/littleorgans/transport-matters",
        "Repository": "https://github.com/littleorgans/transport-matters",
        "Issues": "https://github.com/littleorgans/transport-matters/issues",
        "Changelog": "https://github.com/littleorgans/transport-matters/releases",
    }
    assert project["scripts"] == {"transport-matters": "transport_matters.cli:main"}


def test_transport_matters_version_fallback_uses_distribution_name() -> None:
    init_py = Path(__file__).resolve().parents[1] / "src/transport_matters/__init__.py"

    assert 'version("transport-matters")' in init_py.read_text()
