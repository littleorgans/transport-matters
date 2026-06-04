import ast
from pathlib import Path


def is_test(path: str) -> bool:
    base = path.split("/")[-1]
    return (
        base.startswith("test_")
        or base.endswith("_support.py")
        or "fixtures" in base
        or base == "conftest.py"
    )


def violations() -> list[tuple[str, str]]:
    roots = [Path("src/transport_matters"), Path("tests")]
    out: list[tuple[str, str]] = []

    for root in roots:
        for path in sorted(root.rglob("*.py")):
            rel = str(path)
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
