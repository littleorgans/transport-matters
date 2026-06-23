"""Import guard tests for desktop runtime seams."""

from __future__ import annotations

import subprocess
import sys


def test_desktop_runtime_seams_import_in_fresh_subprocess() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import transport_matters.atomic_io; "
                "import transport_matters.loopback; "
                "import transport_matters.desktop_event; "
                "import transport_matters.desktop_runtime"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
