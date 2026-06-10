from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_session_dao_modules_import_in_subprocess() -> None:
    src_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    pythonpath = str(src_root)
    if existing := env.get("PYTHONPATH"):
        pythonpath = os.pathsep.join((pythonpath, existing))
    env["PYTHONPATH"] = pythonpath

    for module in (
        "transport_matters.session.dao_rows",
        "transport_matters.session.dao_statements",
        "transport_matters.session.dao",
        "transport_matters.session.async_dao",
        "transport_matters.session",
    ):
        result = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0, result.stderr
