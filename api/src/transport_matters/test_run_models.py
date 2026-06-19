from __future__ import annotations

import subprocess
import sys


def test_run_models_imports_in_fresh_process() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import transport_matters.run_models"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
