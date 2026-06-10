from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_package_root_terminal_modules_import_in_subprocess() -> None:
    src_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    pythonpath = str(src_root)
    if existing := env.get("PYTHONPATH"):
        pythonpath = os.pathsep.join((pythonpath, existing))
    env["PYTHONPATH"] = pythonpath

    for module in (
        "transport_matters.captured_run_models",
        "transport_matters.pty_session",
        "transport_matters.run_terminal",
        "transport_matters.run_manager",
    ):
        result = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0, result.stderr
