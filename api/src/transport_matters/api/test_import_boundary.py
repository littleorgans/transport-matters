from __future__ import annotations

import ast
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parent
_PACKAGE_ROOT = _API_ROOT.parent


def _module_name(path: Path) -> str:
    rel = path.relative_to(_PACKAGE_ROOT).with_suffix("")
    parts = ["transport_matters", *rel.parts]
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _import_from_targets(path: Path, node: ast.ImportFrom) -> list[str]:
    base = node.module or ""
    if node.level:
        current_module = _module_name(path)
        current_package = (
            current_module if path.name == "__init__.py" else current_module.rsplit(".", 1)[0]
        )
        package_parts = current_package.split(".")
        parent = ".".join(package_parts[: len(package_parts) - node.level + 1])
        base = f"{parent}.{base}" if base else parent

    targets = [base] if base else []
    targets.extend(f"{base}.{alias.name}" if base else alias.name for alias in node.names)
    return targets


def _imports_cli(target: str) -> bool:
    return target == "transport_matters.cli" or target.startswith("transport_matters.cli.")


def _api_cli_import_violations() -> list[str]:
    violations: list[str] = []
    for path in sorted(_API_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                targets = _import_from_targets(path, node)
            for target in targets:
                if _imports_cli(target):
                    rel = path.relative_to(_PACKAGE_ROOT)
                    line_no = getattr(node, "lineno", 0)
                    violations.append(f"{rel}:{line_no}: {target}")
    return violations


def test_api_layer_does_not_import_cli_layer() -> None:
    violations = _api_cli_import_violations()
    assert not violations, "api layer imports cli layer:\n" + "\n".join(violations)
