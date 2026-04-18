"""Disk-backed storage backend.

Persists exchange artifacts and index to ``~/.manicure/exchanges/``
(configurable).  Uses ``aiofiles`` for non-blocking file I/O.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
from concurrent.futures import Executor, ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, cast

import aiofiles

from manicure.ir import InternalRequest, InternalResponse
from manicure.storage.base import (
    ExchangeArtifacts,
    IndexEntry,
    StorageBackend,
    TransportArtifacts,
)
from manicure.transport_redaction import redact_transport_artifacts

logger = logging.getLogger(__name__)

_DEFAULT_ROOT = Path.home() / ".manicure" / "exchanges"


class DiskStorageBackend(StorageBackend):
    """Append-only JSONL index with per-exchange artifact directories."""

    def __init__(self, root: str | Path | None = None) -> None:
        self._root = Path(root) if root else _DEFAULT_ROOT
        self._root.mkdir(parents=True, exist_ok=True)
        self._index_lock = asyncio.Lock()
        self._index_cache: dict[str, IndexEntry] | None = None
        self._io_executor: Executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="manicure-storage",
        )
        self._cleanup_partial_writes()

    @property
    def root(self) -> Path:
        return self._root

    # ── index ───────────────────────────────────────────────────────

    async def _ensure_index_cache(self) -> dict[str, IndexEntry]:
        """Build the id→IndexEntry cache if not yet loaded.

        Must be called while holding ``_index_lock``.
        """
        if self._index_cache is not None:
            return self._index_cache
        entries: dict[str, IndexEntry] = {}
        index_path = self._root / "index.jsonl"
        if index_path.exists():
            lines = await self._read_lines(index_path)
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                pos, decoder = 0, json.JSONDecoder()
                while pos < len(line):
                    try:
                        obj, end = decoder.raw_decode(line, pos)
                        entry = IndexEntry.model_validate(obj)
                        entries[entry.id] = entry
                        pos = end
                    except (json.JSONDecodeError, Exception) as exc:
                        logger.warning(
                            "Skipping malformed index entry at pos %d: %s", pos, exc
                        )
                        break

        # Historical rows written before ResStats carried
        # cache_creation_input_tokens stored a zero for that field. The full
        # UsageStats survives in the per-exchange response.ir.json artifact,
        # so we can recover the missing value on first read and rewrite the
        # index in place. Rows where the artifact also reports zero stay
        # untouched — the probe is cheap and only runs until every row has
        # a nonzero value or has been confirmed zero by the artifact.
        corrected = await self._backfill_cache_creation(entries)
        if corrected > 0:
            logger.info(
                "Backfilled cache_creation_input_tokens on %d index row(s)",
                corrected,
            )
            await self._rewrite_index(entries)

        self._index_cache = entries
        return entries

    async def _backfill_cache_creation(self, entries: dict[str, IndexEntry]) -> int:
        """Mutate ``entries`` in place, replacing rows whose ResStats has
        ``cache_creation_input_tokens == 0`` with the value from the on-disk
        ``response.ir.json`` artifact, when the artifact reports non-zero.

        Returns the count of corrected rows.
        """
        # Pre-index directory names once so each backfill lookup is O(1)
        # rather than O(n) through _find_exchange_dir.
        dir_by_short: dict[str, Path] = {}
        if self._root.exists():
            for d in self._root.iterdir():
                if d.is_dir() and not d.name.endswith(".tmp"):
                    short = d.name.rsplit("-", 1)[-1]
                    dir_by_short[short] = d

        corrected = 0
        for exchange_id, entry in list(entries.items()):
            if entry.res is None or entry.res.cache_creation_input_tokens != 0:
                continue
            exchange_dir = dir_by_short.get(exchange_id[:8])
            if exchange_dir is None:
                continue
            resp_ir_path = exchange_dir / "response.ir.json"
            if not resp_ir_path.exists():
                continue
            try:
                resp_json = await self._read_text(resp_ir_path)
                resp_ir = InternalResponse.model_validate_json(resp_json)
            except Exception as exc:
                logger.debug("Skipping backfill for %s: %s", exchange_id, exc)
                continue
            cc = resp_ir.usage.cache_creation_input_tokens
            if cc == 0:
                continue
            entries[exchange_id] = entry.model_copy(
                update={
                    "res": entry.res.model_copy(
                        update={"cache_creation_input_tokens": cc}
                    )
                }
            )
            corrected += 1
        return corrected

    async def _rewrite_index(self, entries: dict[str, IndexEntry]) -> None:
        """Atomically rewrite index.jsonl from an in-memory cache snapshot.

        Used only by the cache_creation backfill path. Write to a sibling
        ``.tmp`` file and rename so a crashed rewrite leaves the original
        index intact.
        """
        index_path = self._root / "index.jsonl"
        tmp_path = index_path.with_name("index.jsonl.tmp")
        body = "".join(entry.model_dump_json() + "\n" for entry in entries.values())
        await self._write_text(tmp_path, body)
        tmp_path.rename(index_path)

    async def append_index(self, entry: IndexEntry) -> None:
        index_path = self._root / "index.jsonl"
        line = entry.model_dump_json() + "\n"
        async with self._index_lock:
            await self._write_text(index_path, line, mode="a")
            if self._index_cache is not None:
                self._index_cache[entry.id] = entry

    async def upsert_index(self, entry: IndexEntry) -> None:
        index_path = self._root / "index.jsonl"
        line = entry.model_dump_json() + "\n"
        async with self._index_lock:
            cache = await self._ensure_index_cache()
            if entry.id in cache:
                cache[entry.id] = entry
                await self._rewrite_index(cache)
                return
            await self._write_text(index_path, line, mode="a")
            cache[entry.id] = entry

    async def persist_exchange(
        self, entry: IndexEntry, artifacts: ExchangeArtifacts
    ) -> None:
        final_dir, tmp_dir = self._prepare_exchange_write(entry.id, artifacts)
        backup_dir: Path | None = None

        try:
            await self._write_exchange_files(tmp_dir, artifacts)
            backup_dir = await self._activate_exchange_dir(tmp_dir, final_dir)
            try:
                async with self._index_lock:
                    cache = await self._ensure_index_cache()
                    previous_entry = cache.get(entry.id)
                    cache[entry.id] = entry
                    try:
                        await self._rewrite_index(cache)
                    except BaseException:
                        if previous_entry is None:
                            cache.pop(entry.id, None)
                        else:
                            cache[entry.id] = previous_entry
                        raise
            except BaseException:
                await self._rollback_activated_exchange(final_dir, backup_dir)
                raise
            await self._cleanup_exchange_backup(backup_dir)
        except BaseException:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    async def read_index(
        self, limit: int, offset: int, run_id: str | None = None
    ) -> list[IndexEntry]:
        async with self._index_lock:
            cache = await self._ensure_index_cache()
        entries = list(cache.values())
        if run_id is not None:
            entries = [entry for entry in entries if entry.run_id == run_id]
        return entries[offset : offset + limit]

    async def read_index_entry(self, exchange_id: str) -> IndexEntry | None:
        async with self._index_lock:
            cache = await self._ensure_index_cache()
            return cache.get(exchange_id)

    async def delete_exchange(self, exchange_id: str) -> bool:
        """Delete an exchange row and artifact directory if present."""
        removed = False
        exchange_dir = self._find_exchange_dir_or_none(exchange_id)

        async with self._index_lock:
            cache = await self._ensure_index_cache()
            previous_entry = cache.get(exchange_id)
            if previous_entry is not None:
                previous_items = tuple(cache.items())
                cache.pop(exchange_id, None)
                try:
                    await self._rewrite_index(cache)
                except BaseException:
                    cache.clear()
                    cache.update(previous_items)
                    raise
                removed = True

        if exchange_dir is not None and exchange_dir.exists():
            await self._run_io(shutil.rmtree, exchange_dir, True)
            removed = True

        return removed

    async def update_pipeline_tokens(
        self,
        exchange_id: str,
        tokens_before: int | None,
        tokens_after: int | None,
    ) -> IndexEntry | None:
        """Stamp pipeline token counts onto an existing IndexEntry.

        Silently skips (returns None) when the exchange is missing or has
        no pipeline record. Rewrites the index via the same `.tmp` + rename
        pattern as the cache_creation backfill so a crashed rewrite leaves
        the original index intact.
        """
        async with self._index_lock:
            cache = await self._ensure_index_cache()
            entry = cache.get(exchange_id)
            if entry is None or entry.pipeline is None:
                return None
            updated_pipeline = entry.pipeline.model_copy(
                update={
                    "tokens_before": tokens_before,
                    "tokens_after": tokens_after,
                }
            )
            updated_entry = entry.model_copy(update={"pipeline": updated_pipeline})
            cache[exchange_id] = updated_entry
            try:
                await self._rewrite_index(cache)
            except BaseException:
                cache[exchange_id] = entry
                raise
            return updated_entry

    # ── exchange artifacts ──────────────────────────────────────────

    async def write_exchange(
        self, exchange_id: str, artifacts: ExchangeArtifacts
    ) -> None:
        final_dir, tmp_dir = self._prepare_exchange_write(exchange_id, artifacts)
        try:
            await self._write_exchange_files(tmp_dir, artifacts)
            backup_dir = await self._activate_exchange_dir(tmp_dir, final_dir)
            await self._cleanup_exchange_backup(backup_dir)
        except BaseException:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    async def read_exchange(self, exchange_id: str) -> ExchangeArtifacts:
        exchange_dir = self._find_exchange_dir(exchange_id)

        request_raw = await self._read_bytes(exchange_dir / "request.raw")

        request_ir_json = await self._read_text(exchange_dir / "request.ir.json")
        request_ir = InternalRequest.model_validate_json(request_ir_json)

        request_curated_raw: bytes | None = None
        curated_raw_path = exchange_dir / "request.curated.raw"
        if curated_raw_path.exists():
            request_curated_raw = await self._read_bytes(curated_raw_path)

        curated_path = exchange_dir / "request.curated.ir.json"
        request_curated_ir: InternalRequest | None = None
        if curated_path.exists():
            curated_json = await self._read_text(curated_path)
            request_curated_ir = InternalRequest.model_validate_json(curated_json)

        request_audit = None
        audit_path = exchange_dir / "request.audit.json"
        if audit_path.exists():
            audit_json = await self._read_text(audit_path)
            from manicure.overrides import OverrideAudit

            request_audit = OverrideAudit.model_validate_json(audit_json)

        response_raw: bytes | None = None
        resp_raw_path = exchange_dir / "response.raw"
        if resp_raw_path.exists():
            response_raw = await self._read_bytes(resp_raw_path)

        response_ir: InternalResponse | None = None
        resp_ir_path = exchange_dir / "response.ir.json"
        if resp_ir_path.exists():
            resp_ir_json = await self._read_text(resp_ir_path)
            response_ir = InternalResponse.model_validate_json(resp_ir_json)

        transport: TransportArtifacts | None = None
        transport_path = exchange_dir / "transport.json"
        if transport_path.exists():
            transport_json = await self._read_text(transport_path)
            transport = TransportArtifacts.model_validate_json(transport_json)
            transport, changed = redact_transport_artifacts(transport)
            if changed and transport is not None:
                await self._rewrite_transport_json(transport_path, transport)

        return ExchangeArtifacts(
            request_raw=request_raw,
            request_ir=request_ir,
            request_curated_raw=request_curated_raw,
            request_curated_ir=request_curated_ir,
            request_audit=request_audit,
            response_raw=response_raw,
            response_ir=response_ir,
            transport=transport,
        )

    # ── private helpers ─────────────────────────────────────────────

    def _exchange_dir(self, exchange_id: str, artifacts: ExchangeArtifacts) -> Path:
        """Build the per-exchange directory path: ``{ts_slug}-{id[:8]}/``."""
        ts = datetime.now(tz=UTC)
        ts_slug = ts.strftime("%Y%m%dT%H%M%SZ")
        return self._root / f"{ts_slug}-{exchange_id[:8]}"

    def _find_exchange_dir(self, exchange_id: str) -> Path:
        """Locate an exchange directory by its ID prefix."""
        exchange_dir = self._find_exchange_dir_or_none(exchange_id)
        if exchange_dir is not None:
            return exchange_dir
        msg = f"Exchange directory not found for {exchange_id}"
        raise FileNotFoundError(msg)

    def _find_exchange_dir_or_none(self, exchange_id: str) -> Path | None:
        """Locate an exchange directory by its ID prefix, or return None."""
        short = exchange_id[:8]
        for d in self._root.iterdir():
            if d.is_dir() and d.name.endswith(f"-{short}"):
                return d
        return None

    def _prepare_exchange_write(
        self, exchange_id: str, artifacts: ExchangeArtifacts
    ) -> tuple[Path, Path]:
        final_dir = self._find_exchange_dir_or_none(exchange_id) or self._exchange_dir(
            exchange_id, artifacts
        )
        tmp_dir = final_dir.parent / f"{final_dir.name}.tmp"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return final_dir, tmp_dir

    async def _write_exchange_files(
        self, tmp_dir: Path, artifacts: ExchangeArtifacts
    ) -> None:
        await self._write_bytes(tmp_dir / "request.raw", artifacts.request_raw)

        ir_json = artifacts.request_ir.model_dump_json(indent=2)
        await self._write_text(tmp_dir / "request.ir.json", ir_json)

        if artifacts.request_curated_raw is not None:
            await self._write_bytes(
                tmp_dir / "request.curated.raw",
                artifacts.request_curated_raw,
            )

        if artifacts.request_curated_ir is not None:
            curated_json = artifacts.request_curated_ir.model_dump_json(indent=2)
            await self._write_text(
                tmp_dir / "request.curated.ir.json",
                curated_json,
            )

        if artifacts.request_audit is not None:
            audit_json = artifacts.request_audit.model_dump_json(indent=2)
            await self._write_text(tmp_dir / "request.audit.json", audit_json)

        if artifacts.response_raw is not None:
            await self._write_bytes(tmp_dir / "response.raw", artifacts.response_raw)

        if artifacts.response_ir is not None:
            resp_json = artifacts.response_ir.model_dump_json(indent=2)
            await self._write_text(tmp_dir / "response.ir.json", resp_json)

        if artifacts.transport is not None:
            sanitized_transport, _ = redact_transport_artifacts(artifacts.transport)
            if sanitized_transport is not None:
                await self._write_transport_json(
                    tmp_dir / "transport.json",
                    sanitized_transport,
                )

    async def _activate_exchange_dir(
        self, tmp_dir: Path, final_dir: Path
    ) -> Path | None:
        """Swap a staged exchange dir into place and keep any backup for rollback."""
        backup_dir = final_dir.parent / f"{final_dir.name}.bak"
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
        """Remove leftover ``.tmp`` directories from interrupted writes."""
        if not self._root.exists():
            return
        for d in self._root.iterdir():
            if d.is_dir() and d.name.endswith(".tmp"):
                logger.warning("Cleaning up partial write: %s", d)
                shutil.rmtree(d, ignore_errors=True)

    async def _write_transport_json(
        self,
        path: Path,
        transport: TransportArtifacts,
    ) -> None:
        transport_json = transport.model_dump_json(indent=2)
        await self._write_text(path, transport_json)

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
