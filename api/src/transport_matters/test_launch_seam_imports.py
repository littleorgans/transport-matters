"""Import guards for neutral launch seam modules."""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "transport_matters.launch_environment",
        "transport_matters.launch_manifest",
        "transport_matters.session_store_preflight",
        "transport_matters.cli.launch_runtime",
        "transport_matters.cli.codex_cmd",
        "transport_matters.captured_codex",
        "transport_matters.captured_run_context",
        "transport_matters.captured_run",
    ],
)
def test_launch_seam_imports_cleanly(module: str) -> None:
    src_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(src_root) if pythonpath is None else f"{src_root}{os.pathsep}{pythonpath}"
    )
    completed = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=src_root.parent,
        env=env,
        capture_output=True,
        check=False,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


_CAPTURED_RUN_CYCLE_MODULES = {
    "transport_matters.captured_codex",
    "transport_matters.captured_run",
    "transport_matters.captured_run_context",
    "transport_matters.cli.codex_cmd",
}


def test_captured_run_codex_launch_modules_stay_acyclic() -> None:
    src_root = Path(__file__).resolve().parents[1]
    graph = {module: _local_imports(src_root, module) for module in _CAPTURED_RUN_CYCLE_MODULES}
    cycle = _find_cycle(graph)
    assert cycle is None, " -> ".join(cycle or ())


def _local_imports(src_root: Path, module: str) -> set[str]:
    path = src_root.joinpath(*module.split(".")).with_suffix(".py")
    tree = ast.parse(path.read_text())
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(
                alias.name for alias in node.names if alias.name in _CAPTURED_RUN_CYCLE_MODULES
            )
        elif isinstance(node, ast.ImportFrom):
            imported_module = _resolve_import_from(module, node)
            if imported_module in _CAPTURED_RUN_CYCLE_MODULES:
                imports.add(imported_module)
            if imported_module is not None:
                imports.update(
                    f"{imported_module}.{alias.name}"
                    for alias in node.names
                    if f"{imported_module}.{alias.name}" in _CAPTURED_RUN_CYCLE_MODULES
                )
    return imports


def _resolve_import_from(module: str, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    package_parts = module.rsplit(".", 1)[0].split(".")
    if node.level > len(package_parts):
        return None
    base = ".".join(package_parts[: len(package_parts) - node.level + 1])
    return base if node.module is None else f"{base}.{node.module}"


def _find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    visited: set[str] = set()
    active: list[str] = []

    def visit(module: str) -> list[str] | None:
        if module in active:
            return [*active[active.index(module) :], module]
        if module in visited:
            return None
        active.append(module)
        for imported in graph[module]:
            cycle = visit(imported)
            if cycle is not None:
                return cycle
        active.pop()
        visited.add(module)
        return None

    for module in graph:
        cycle = visit(module)
        if cycle is not None:
            return cycle
    return None
