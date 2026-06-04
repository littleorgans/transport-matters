import ast
from pathlib import Path

# Anchor scan roots to this file's location, not the process cwd, so the lint
# scans the same trees regardless of where pytest is invoked from. A cwd-relative
# root silently scans nothing (and false-passes) when run from anywhere but api/.
_PKG_ROOT = Path(__file__).resolve().parent  # api/src/transport_matters
_API_ROOT = _PKG_ROOT.parents[1]  # api
_SCAN_ROOTS = [_PKG_ROOT, _API_ROOT / "tests"]


def is_test(path: str) -> bool:
    base = path.split("/")[-1]
    return (
        base.startswith("test_")
        or base.endswith("_support.py")
        or "fixtures" in base
        or base == "conftest.py"
    )


def violations() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []

    for root in _SCAN_ROOTS:
        assert root.is_dir(), f"private-import scan root missing: {root}"
        for path in sorted(root.rglob("*.py")):
            rel = str(path.relative_to(_API_ROOT))
            if is_test(rel):
                continue

            try:
                tree = ast.parse(path.read_text(), rel)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue

                module = node.module or ""
                if not (module.startswith("transport_matters") or node.level):
                    continue

                leaf = module.split(".")[-1] if module else ""
                if leaf.startswith("_") and not leaf.startswith("__"):
                    out.append((rel, f"private module {module}"))

                for alias in node.names:
                    if alias.name.startswith("_") and not alias.name.startswith("__"):
                        out.append((rel, f"{alias.name} from {module or '.' * node.level}"))

    return out


def test_private_import_boundary() -> None:
    offenders = violations()
    lines = [f"{path}: {reason}" for path, reason in offenders]
    assert not offenders, "private import boundary violations:\n" + "\n".join(sorted(lines))
