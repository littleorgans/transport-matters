"""High level `manicure.supervisor` façade checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from manicure.supervisor import ProcessSupervisor

pytest_plugins = ("manicure.test_supervisor_support",)
pytestmark = pytest.mark.usefixtures("patched_popen")

if TYPE_CHECKING:
    from pathlib import Path


def test_get_returns_managed_process(tmp_log: Path) -> None:
    sup = ProcessSupervisor()
    mp = sup.spawn("mitmdump", ["mitmdump"], log_path=tmp_log)
    assert sup.get("mitmdump") is mp


def test_get_unknown_name_raises() -> None:
    sup = ProcessSupervisor()
    with pytest.raises(KeyError):
        sup.get("ghost")
