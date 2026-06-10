"""Import guards for neutral launch seam modules."""

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
