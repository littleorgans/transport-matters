from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_pty_session_imports_in_subprocess() -> None:
    src_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    pythonpath = str(src_root)
    if existing := env.get("PYTHONPATH"):
        pythonpath = os.pathsep.join((pythonpath, existing))
    env["PYTHONPATH"] = pythonpath

    result = subprocess.run(
        [sys.executable, "-c", "import transport_matters.pty_session"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
