from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import aiofiles

from manicure.codex.events import CodexTurnSummary
from manicure.ir import InternalRequest, InternalResponse, TextBlock, ToolUseBlock
from manicure.overrides import OverrideAudit, count_chars_parts
from manicure.storage.base import (
    CodexTurnListSummary,
    IndexEntry,
    PipelineStats,
    ReqStats,
    ResStats,
    TransportArtifacts,
)

if TYPE_CHECKING:
    from concurrent.futures import Executor
    from datetime import datetime

    from manicure.storage.disk_layout import DiskStorageLayout

logger = logging.getLogger(__name__)


class DiskStorageFileOpsMixin:
    _root: Path
    _layout: DiskStorageLayout
    _io_executor: Executor

    async def _write_entry_json(self, path: Path, entry: IndexEntry) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(entry.model_dump_json(indent=2))
        tmp_path.replace(path)

    async def _activate_exchange_dir(
        self, tmp_dir: Path, final_dir: Path
    ) -> Path | None:
        backup_dir = self._layout.backup_exchange_dir(final_dir)
        if backup_dir.exists():
            if final_dir.exists():
                await self._run_io(shutil.rmtree, backup_dir, True)
            else:
                backup_dir.rename(final_dir)

        had_existing = final_dir.exists()
        if had_existing:
            final_dir.rename(backup_dir)

        try:
            tmp_dir.rename(final_dir)
        except Exception:
            if had_existing and backup_dir.exists() and not final_dir.exists():
                try:
                    backup_dir.rename(final_dir)
                except Exception:
                    logger.exception(
                        "Failed to restore exchange dir %s after rewrite failure",
                        final_dir,
                    )
            raise

        return backup_dir if had_existing else None

    async def _stage_exchange_delete(self, final_dir: Path) -> Path:
        staged_dir = self._layout.staged_delete_dir(final_dir)
        if staged_dir.exists():
            await self._run_io(shutil.rmtree, staged_dir, True)
        final_dir.rename(staged_dir)
        return staged_dir

    async def _restore_staged_delete(self, staged_dir: Path, final_dir: Path) -> None:
        if not staged_dir.exists():
            return
        if final_dir.exists():
            await self._run_io(shutil.rmtree, final_dir, True)
        staged_dir.rename(final_dir)

    async def _rollback_activated_exchange(
        self, final_dir: Path, backup_dir: Path | None
    ) -> None:
        if backup_dir is not None and backup_dir.exists():
            if final_dir.exists():
                await self._run_io(shutil.rmtree, final_dir, True)
            backup_dir.rename(final_dir)
            return
        if final_dir.exists():
            await self._run_io(shutil.rmtree, final_dir, True)

    async def _cleanup_exchange_backup(self, backup_dir: Path | None) -> None:
        if backup_dir is None or not backup_dir.exists():
            return
        try:
            await self._run_io(shutil.rmtree, backup_dir, True)
        except Exception:
            logger.warning(
                "Failed to remove exchange dir backup %s", backup_dir, exc_info=True
            )

    def _cleanup_partial_writes(self) -> None:
        if not self._root.exists():
            return
        for d in self._root.iterdir():
            if self._layout.is_tmp_exchange_dir(d):
                logger.warning("Cleaning up partial write: %s", d)
                shutil.rmtree(d, ignore_errors=True)
                continue
            if self._layout.is_backup_exchange_dir(d):
                final_dir = self._layout.live_dir_for_backup(d)
                if final_dir.exists():
                    logger.warning("Cleaning up stale exchange backup: %s", d)
                    shutil.rmtree(d, ignore_errors=True)
                    continue
                logger.warning("Restoring interrupted exchange backup: %s", d)
                d.rename(final_dir)

    async def _open(self, path: Path, mode: str = "r") -> Any:
        return await aiofiles.open(  # type: ignore[call-overload]
            str(path),
            mode=mode,
            executor=self._io_executor,
        )

    async def _read_lines(self, path: Path) -> list[str]:
        handle = await self._open(path)
        try:
            return cast("list[str]", await handle.readlines())
        finally:
            await handle.close()

    async def _read_text(self, path: Path) -> str:
        handle = await self._open(path)
        try:
            return cast("str", await handle.read())
        finally:
            await handle.close()

    async def _read_bytes(self, path: Path) -> bytes:
        handle = await self._open(path, mode="rb")
        try:
            return cast("bytes", await handle.read())
        finally:
            await handle.close()

    async def _write_text(self, path: Path, content: str, *, mode: str = "w") -> None:
        handle = await self._open(path, mode=mode)
        try:
            await handle.write(content)
        finally:
            await handle.close()

    async def _write_bytes(
        self,
        path: Path,
        content: bytes,
        *,
        mode: str = "wb",
    ) -> None:
        handle = await self._open(path, mode=mode)
        try:
            await handle.write(content)
        finally:
            await handle.close()

    async def _run_io(self, func: Any, *args: object) -> Any:
        loop = asyncio.get_running_loop()
        bound = partial(func, *args)
        return await loop.run_in_executor(self._io_executor, bound)

    async def _rewrite_transport_json(
        self,
        path: Path,
        transport: TransportArtifacts,
    ) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(transport.model_dump_json(indent=2))
        tmp_path.replace(path)


class DiskStorageRecoveryMixin(DiskStorageFileOpsMixin):
    _root: Path

    async def _reconcile_staged_deletes(self, entries: dict[str, IndexEntry]) -> int:
        reconciled = 0
        for d in self._root.iterdir():
            if not self._layout.is_staged_delete_dir(d):
                continue
            live_dir = self._layout.live_dir_for_staged_delete(d)
            live_name = live_dir.name
            index_entry = await self._entry_for_exchange_dir(entries, d, live_name)
            if index_entry is None:
                logger.warning("Finalizing interrupted exchange delete: %s", d)
                shutil.rmtree(d, ignore_errors=True)
            elif live_dir.exists():
                logger.warning("Cleaning stale staged delete after restore: %s", d)
                shutil.rmtree(d, ignore_errors=True)
            else:
                logger.warning("Restoring interrupted staged delete: %s", d)
                d.rename(live_dir)
            reconciled += 1
        return reconciled

    async def _entry_for_exchange_dir(
        self,
        entries: dict[str, IndexEntry],
        exchange_dir: Path,
        live_name: str | None = None,
    ) -> IndexEntry | None:
        live_dir_name = live_name or exchange_dir.name
        sidecar = await self._recover_index_entry(exchange_dir)
        if sidecar is not None:
            return entries.get(sidecar.id)
        expected_path = self._layout.exchange_index_path(live_dir_name)
        for entry in entries.values():
            if entry.path == expected_path:
                return entry
        return None

    async def _recover_missing_index_entries(
        self,
        entries: dict[str, IndexEntry],
    ) -> int:
        recovered = 0
        for exchange_dir in self._root.iterdir():
            if not self._layout.should_recover_exchange_dir(exchange_dir):
                continue
            entry = await self._recover_index_entry(exchange_dir)
            if entry is None or entry.id in entries:
                continue
            entries[entry.id] = entry
            recovered += 1
        return recovered

    async def _recover_index_entry(self, exchange_dir: Path) -> IndexEntry | None:
        paths = self._layout.artifact_paths(exchange_dir)
        if paths.entry.exists():
            try:
                return IndexEntry.model_validate_json(
                    await self._read_text(paths.entry)
                )
            except Exception:
                logger.warning(
                    "Failed to read exchange entry sidecar for %s",
                    exchange_dir,
                    exc_info=True,
                )

        turn = await self._read_turn_or_none(paths.turn)
        if turn is None:
            return None
        if not self._layout.matches_exchange_id(exchange_dir, turn.exchange_id):
            logger.warning(
                "Skipping exchange dir %s with mismatched turn identity %s",
                exchange_dir,
                turn.exchange_id,
            )
            return None

        request_ir = InternalRequest.model_validate_json(
            await self._read_text(paths.request_ir)
        )
        request_curated_ir = await self._read_request_curated_ir_or_none(
            paths.request_curated_ir
        )
        request_audit = await self._read_request_audit_or_none(paths.request_audit)
        response_ir = await self._read_response_ir_or_none(paths.response_ir)
        ts = self._exchange_timestamp(exchange_dir)
        path = self._layout.exchange_index_path(exchange_dir.name)
        req_ir = request_curated_ir or request_ir
        return IndexEntry(
            id=turn.exchange_id,
            run_id=None,
            ts=ts,
            provider=request_ir.provider,
            model=request_ir.model,
            path=path,
            req=self._req_stats(req_ir),
            pipeline=self._pipeline_stats(request_audit),
            res=self._recovered_res_stats(response_ir, turn),
            codex_turn=CodexTurnListSummary.from_turn(turn),
            mutated_manually=False,
        )

    async def _read_turn_or_none(self, path: Path) -> CodexTurnSummary | None:
        if not path.exists():
            return None
        try:
            return CodexTurnSummary.model_validate_json(await self._read_text(path))
        except Exception:
            logger.warning(
                "Failed to read Codex turn sidecar for %s", path, exc_info=True
            )
            return None

    async def _read_request_curated_ir_or_none(
        self, path: Path
    ) -> InternalRequest | None:
        if not path.exists():
            return None
        return InternalRequest.model_validate_json(await self._read_text(path))

    async def _read_request_audit_or_none(self, path: Path) -> OverrideAudit | None:
        if not path.exists():
            return None
        return OverrideAudit.model_validate_json(await self._read_text(path))

    async def _read_response_ir_or_none(self, path: Path) -> InternalResponse | None:
        if not path.exists():
            return None
        return InternalResponse.model_validate_json(await self._read_text(path))

    def _exchange_timestamp(self, exchange_dir: Path) -> datetime:
        return self._layout.exchange_timestamp(exchange_dir)

    def _req_stats(self, ir: InternalRequest) -> ReqStats:
        system_chars, tools_chars, messages_chars = count_chars_parts(ir)
        return ReqStats(
            system_parts=len(ir.system),
            system_chars=system_chars,
            tools_count=len(ir.tools),
            tools_chars=tools_chars,
            messages_count=sum(len(message.content) for message in ir.messages),
            messages_chars=messages_chars,
            total_chars=system_chars + tools_chars + messages_chars,
        )

    def _pipeline_stats(self, audit: OverrideAudit | None) -> PipelineStats | None:
        if audit is None:
            return None
        return PipelineStats(
            overrides_applied=list(audit.entries),
            chars_before=audit.chars_before,
            chars_after=audit.chars_after,
        )

    def _recovered_res_stats(
        self,
        response_ir: InternalResponse | None,
        turn: CodexTurnSummary,
    ) -> ResStats | None:
        if response_ir is not None:
            text_chars = 0
            tool_calls = 0
            for block in response_ir.content:
                if isinstance(block, TextBlock):
                    text_chars += len(block.text)
                elif isinstance(block, ToolUseBlock):
                    tool_calls += 1
            return ResStats(
                stop_reason=response_ir.stop_reason,
                input_tokens=response_ir.usage.input_tokens,
                output_tokens=response_ir.usage.output_tokens,
                cache_creation_input_tokens=response_ir.usage.cache_creation_input_tokens,
                cache_read_input_tokens=response_ir.usage.cache_read_input_tokens,
                text_chars=text_chars,
                tool_calls=tool_calls,
            )
        if turn.status == "open":
            return None
        return ResStats(
            stop_reason=turn.stop_reason,
            text_chars=turn.text_chars,
            tool_calls=turn.tool_calls,
        )
