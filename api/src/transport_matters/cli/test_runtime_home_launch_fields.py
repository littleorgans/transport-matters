from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from transport_matters.index.adapters.base import (
    FileTailSource,
    SessionBinding,
    encode_source_descriptor,
)
from transport_matters.session.ingest import build_session

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from transport_matters.storage.base import StorageBackend


async def test_launch_fields_carrier_reaches_owned_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from transport_matters import addon_runtime
    from transport_matters.addon_runtime import _register_owned_cursor
    from transport_matters.config import Settings

    captured: dict[str, Any] = {}
    template_provenance = {"template_id": "codex/base", "template_home": "/templates/codex"}

    class FakeAdapter:
        provider = "codex"
        cli = "codex"

        async def bind(self, run: Any) -> SessionBinding:
            return SessionBinding(
                session_id="session-1",
                provider=self.provider,
                run_id=run.run_id,
                cwd=run.cwd,
                workspace_slug=run.workspace_slug,
                workspace_hash=run.workspace_hash,
                started_at=run.started_at,
                cli=self.cli,
                native_session_id=run.native_session_id,
            )

    async def fake_register_session_cursor(
        _tailer: Any, _adapter: Any, binding: SessionBinding
    ) -> None:
        captured["template_provenance"] = binding.template_provenance
        captured["parent_session_id"] = binding.parent_session_id
        captured["forked_at_seq"] = binding.forked_at_seq
        captured["session_purpose"] = cast("Any", binding).session_purpose
        captured["source_descriptor"] = binding.source_descriptor

    monkeypatch.setattr(addon_runtime, "get_adapter", lambda _cli: FakeAdapter())
    monkeypatch.setattr(
        addon_runtime,
        "register_session_cursor",
        fake_register_session_cursor,
    )

    settings = Settings(
        run_id="run-1",
        cwd=tmp_path,
        cli="codex",
        owned_native_session_id="native-1",
        owned_source_descriptor="descriptor-1",
        launch_fields={
            "template_provenance": template_provenance,
            "parent_session_id": "parent-session",
            "forked_at_seq": 4,
            "session_purpose": "continuation",
        },
    )
    binding = addon_runtime.build_proxy_run_binding(settings, cast("StorageBackend", object()))
    await _register_owned_cursor(cast("Any", object()), binding, "2026-06-15T12:00:00+00:00")

    assert captured == {
        "template_provenance": template_provenance,
        "parent_session_id": "parent-session",
        "forked_at_seq": 4,
        "session_purpose": "continuation",
        "source_descriptor": "descriptor-1",
    }


async def test_register_session_cursor_preserves_launch_fields(tmp_path: Path) -> None:
    from transport_matters.index.tailer import register_session_cursor

    template_provenance = {"template_id": "codex/base", "template_home": "/templates/codex"}
    descriptor = encode_source_descriptor(
        FileTailSource(path=str(tmp_path / "rollout.jsonl"), format="codex_rollout")
    )
    binding = SessionBinding(
        session_id="session-1",
        provider="codex",
        run_id="run-1",
        cwd=str(tmp_path),
        workspace_slug="workspace",
        workspace_hash="hash",
        started_at="2026-06-15T12:00:00+00:00",
        cli="codex",
        native_session_id="native-1",
        source_descriptor=descriptor,
        template_provenance=template_provenance,
        parent_session_id="parent-session",
        forked_at_seq=4,
    ).model_copy(update={"session_purpose": "continuation"})

    class FakeAdapter:
        provider = "codex"
        cli = "codex"

        async def bind(self, _run: Any) -> SessionBinding:
            return binding.model_copy(update={"template_provenance": None})

    class FakeTailer:
        def __init__(self) -> None:
            self.cursor: Any = None

        def register(self, cursor: Any) -> None:
            self.cursor = cursor

    tailer = FakeTailer()
    await register_session_cursor(cast("Any", tailer), cast("Any", FakeAdapter()), binding)

    assert tailer.cursor is not None
    assert tailer.cursor.binding.template_provenance == template_provenance
    assert tailer.cursor.binding.parent_session_id == "parent-session"
    assert tailer.cursor.binding.forked_at_seq == 4
    assert tailer.cursor.binding.session_purpose == "continuation"


def test_template_provenance_is_a_declared_session_field(tmp_path: Path) -> None:
    template_provenance = {
        "template_id": "codex/base",
        "template_home": "/templates/codex",
        "registry_source": "agent-runtimes",
    }
    binding = SessionBinding(
        session_id="session-1",
        provider="codex",
        run_id="run-1",
        cwd=str(tmp_path),
        workspace_slug="workspace",
        workspace_hash="hash",
        started_at="2026-06-15T12:00:00+00:00",
        cli="codex",
        native_session_id="native-1",
        template_provenance=template_provenance,
    )

    row = build_session(binding)

    assert binding.model_dump()["template_provenance"] == template_provenance
    assert row.template_provenance == template_provenance
