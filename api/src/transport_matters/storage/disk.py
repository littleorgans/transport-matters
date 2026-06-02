"""Disk-backed storage backend.

Persists exchange artifacts and index to ``~/.transport-matters/``
(configurable).  Uses ``aiofiles`` for non-blocking file I/O.
"""

import asyncio
import json
import logging
import shutil
from concurrent.futures import Executor, ThreadPoolExecutor
from typing import TYPE_CHECKING

from transport_matters.codex.derivation_codec import (
    serialize_codex_events_jsonl,
    serialize_codex_turn_json,
)
from transport_matters.codex.events import CodexSemanticEvent, CodexTurnSummary
from transport_matters.ir import InternalRequest, InternalResponse
from transport_matters.storage.base import (
    CodexDerivedArtifactFiles,
    ExchangeArtifacts,
    IndexEntry,
    StorageBackend,
    TransportArtifacts,
)
from transport_matters.storage.disk_helpers import DiskStorageRecoveryMixin
from transport_matters.storage.disk_layout import DiskStorageLayout
from transport_matters.transport_redaction import redact_transport_artifacts

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path


class DiskStorageBackend(DiskStorageRecoveryMixin, StorageBackend):
    """Append-only JSONL index with per-exchange artifact directories."""

    def __init__(self, root: str | Path | None = None) -> None:
        self._layout = DiskStorageLayout(root)
        self._root = self._layout.root
        self._drop_legacy_flat_anchor_cache()
        self._root.mkdir(parents=True, exist_ok=True)
        self._index_lock = asyncio.Lock()
        self._index_cache: dict[str, IndexEntry] | None = None
        self._io_executor: Executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="transport-matters-storage",
        )
        self._cleanup_partial_writes()

    @property
    def root(self) -> Path:
        return self._root

    def _drop_legacy_flat_anchor_cache(self) -> None:
        index_path = self._layout.index_path
        if not index_path.exists():
            return
        try:
            lines = index_path.read_text().splitlines()
        except OSError:
            logger.exception("Failed to inspect legacy storage index")
            return
        legacy_keys = {
            "track_spawn_exchange_id",
            "track_spawn_tool_use_id",
            "track_spawn_order",
        }
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and legacy_keys.intersection(payload):
                break
        else:
            return
        logger.info("Dropping legacy Transport Matters storage cache with flat spawn anchor fields")
        shutil.rmtree(self._root, ignore_errors=True)

    # ── index ───────────────────────────────────────────────────────

    async def _ensure_index_cache(self) -> dict[str, IndexEntry]:
        """Build the id→IndexEntry cache if not yet loaded.

        Must be called while holding ``_index_lock``.
        """
        if self._index_cache is not None:
            return self._index_cache
        entries: dict[str, IndexEntry] = {}
        index_path = self._layout.index_path
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
                        logger.warning("Skipping malformed index entry at pos %d: %s", pos, exc)
                        break

        # Historical rows written before ResStats carried
        # cache_creation_input_tokens stored a zero for that field. The full
        # UsageStats survives in the per-exchange response.ir.json artifact,
        # so we can recover the missing value on first read and rewrite the
        # index in place. Rows where the artifact also reports zero stay
        # untouched — the probe is cheap and only runs until every row has
        # a nonzero value or has been confirmed zero by the artifact.
        recovered_delete_dirs = await self._reconcile_staged_deletes(entries)
        recovered_rows = await self._recover_missing_index_entries(entries)
        corrected = await self._backfill_cache_creation(entries)
        if recovered_rows > 0 or corrected > 0:
            logger.info(
                "Recovered %d exchange row(s) and backfilled cache_creation_input_tokens on %d row(s)",
                recovered_rows,
                corrected,
            )
            await self._rewrite_index(entries)
        if recovered_delete_dirs > 0:
            logger.info(
                "Reconciled %d staged exchange delete(s)",
                recovered_delete_dirs,
            )

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
                if d.is_dir() and not self._layout.is_tmp_exchange_dir(d):
                    short = self._layout.short_id_from_dir_name(d.name)
                    dir_by_short[short] = d

        corrected = 0
        for exchange_id, entry in list(entries.items()):
            if entry.res is None or entry.res.cache_creation_input_tokens != 0:
                continue
            exchange_dir = dir_by_short.get(self._layout.short_id(exchange_id))
            if exchange_dir is None:
                continue
            resp_ir_path = self._layout.artifact_paths(exchange_dir).response_ir
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
                update={"res": entry.res.model_copy(update={"cache_creation_input_tokens": cc})}
            )
            corrected += 1
        return corrected

    async def _rewrite_index(self, entries: dict[str, IndexEntry]) -> None:
        """Atomically rewrite index.jsonl from an in-memory cache snapshot.

        Used only by the cache_creation backfill path. Write to a sibling
        ``.tmp`` file and rename so a crashed rewrite leaves the original
        index intact.
        """
        index_path = self._layout.index_path
        tmp_path = self._layout.index_tmp_path
        body = "".join(entry.model_dump_json() + "\n" for entry in entries.values())
        await self._write_text(tmp_path, body)
        tmp_path.rename(index_path)

    async def append_index(self, entry: IndexEntry) -> None:
        index_path = self._layout.index_path
        line = entry.model_dump_json() + "\n"
        async with self._index_lock:
            await self._write_text(index_path, line, mode="a")
            if self._index_cache is not None:
                self._index_cache[entry.id] = entry

    async def upsert_index(self, entry: IndexEntry) -> None:
        index_path = self._layout.index_path
        line = entry.model_dump_json() + "\n"
        async with self._index_lock:
            cache = await self._ensure_index_cache()
            if entry.id in cache:
                cache[entry.id] = entry
                await self._rewrite_index(cache)
                return
            await self._write_text(index_path, line, mode="a")
            cache[entry.id] = entry

    async def persist_exchange(self, entry: IndexEntry, artifacts: ExchangeArtifacts) -> None:
        artifacts.validate_codex_derived_artifacts()
        final_dir, tmp_dir = self._prepare_exchange_write(entry.id, now=entry.ts)
        backup_dir: Path | None = None

        try:
            await self._write_exchange_files(tmp_dir, artifacts)
            await self._write_entry_json(self._layout.artifact_paths(tmp_dir).entry, entry)
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
        self,
        limit: int,
        offset: int,
        run_id: str | None = None,
        track_id: str | None = None,
    ) -> list[IndexEntry]:
        async with self._index_lock:
            cache = await self._ensure_index_cache()
        entries = list(cache.values())
        if run_id is not None:
            entries = [entry for entry in entries if entry.run_id == run_id]
        if track_id is not None:
            entries = [entry for entry in entries if entry.track_id == track_id]
        return entries[offset : offset + limit]

    async def read_index_entry(self, exchange_id: str) -> IndexEntry | None:
        async with self._index_lock:
            cache = await self._ensure_index_cache()
            return cache.get(exchange_id)

    async def delete_exchange(self, exchange_id: str) -> bool:
        """Delete an exchange row and artifact directory if present."""
        removed = False
        exchange_dir = self._find_exchange_dir_or_none(exchange_id)
        staged_dir: Path | None = None

        async with self._index_lock:
            cache = await self._ensure_index_cache()
            previous_entry = cache.get(exchange_id)
            previous_items = tuple(cache.items())
            if exchange_dir is not None and exchange_dir.exists():
                staged_dir = await self._stage_exchange_delete(exchange_dir)
                removed = True
            if previous_entry is not None:
                cache.pop(exchange_id, None)
                try:
                    await self._rewrite_index(cache)
                except BaseException:
                    cache.clear()
                    cache.update(previous_items)
                    if staged_dir is not None:
                        assert exchange_dir is not None
                        await self._restore_staged_delete(staged_dir, exchange_dir)
                    raise
                removed = True

            if staged_dir is not None and staged_dir.exists():
                try:
                    await self._run_io(shutil.rmtree, staged_dir, True)
                except BaseException:
                    cache.clear()
                    cache.update(previous_items)
                    try:
                        await self._rewrite_index(cache)
                    except Exception:
                        logger.exception(
                            "Failed to restore index row for %s after delete cleanup failure",
                            exchange_id,
                        )
                    assert exchange_dir is not None
                    await self._restore_staged_delete(staged_dir, exchange_dir)
                    raise

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

    async def write_exchange(self, exchange_id: str, artifacts: ExchangeArtifacts) -> None:
        artifacts.validate_codex_derived_artifacts()
        final_dir, tmp_dir = self._prepare_exchange_write(exchange_id)
        try:
            await self._write_exchange_files(tmp_dir, artifacts)
            backup_dir = await self._activate_exchange_dir(tmp_dir, final_dir)
            await self._cleanup_exchange_backup(backup_dir)
        except BaseException:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    async def read_exchange(self, exchange_id: str) -> ExchangeArtifacts:
        exchange_dir = self._find_exchange_dir(exchange_id)
        paths = self._layout.artifact_paths(exchange_dir)

        request_raw = await self._read_bytes(paths.request_raw)

        request_ir_json = await self._read_text(paths.request_ir)
        request_ir = InternalRequest.model_validate_json(request_ir_json)

        request_curated_raw: bytes | None = None
        if paths.request_curated_raw.exists():
            request_curated_raw = await self._read_bytes(paths.request_curated_raw)

        request_curated_ir: InternalRequest | None = None
        if paths.request_curated_ir.exists():
            curated_json = await self._read_text(paths.request_curated_ir)
            request_curated_ir = InternalRequest.model_validate_json(curated_json)

        request_audit = None
        if paths.request_audit.exists():
            audit_json = await self._read_text(paths.request_audit)
            from transport_matters.overrides import OverrideAudit

            request_audit = OverrideAudit.model_validate_json(audit_json)

        response_raw: bytes | None = None
        if paths.response_raw.exists():
            response_raw = await self._read_bytes(paths.response_raw)

        response_ir: InternalResponse | None = None
        if paths.response_ir.exists():
            resp_ir_json = await self._read_text(paths.response_ir)
            response_ir = InternalResponse.model_validate_json(resp_ir_json)

        transport: TransportArtifacts | None = None
        if paths.transport.exists():
            transport_json = await self._read_text(paths.transport)
            transport = TransportArtifacts.model_validate_json(transport_json)
            transport, changed = redact_transport_artifacts(transport)
            if changed and transport is not None:
                await self._rewrite_transport_json(paths.transport, transport)

        events: tuple[CodexSemanticEvent, ...] | None = None
        if paths.events.exists():
            try:
                events = await self._read_events_jsonl(paths.events)
            except Exception:
                logger.warning(
                    "Failed to read Codex events sidecar for %s",
                    exchange_id,
                    exc_info=True,
                )

        turn: CodexTurnSummary | None = None
        if paths.turn.exists():
            try:
                turn_json = await self._read_text(paths.turn)
                turn = CodexTurnSummary.model_validate_json(turn_json)
            except Exception:
                logger.warning(
                    "Failed to read Codex turn sidecar for %s",
                    exchange_id,
                    exc_info=True,
                )

        return ExchangeArtifacts(
            request_raw=request_raw,
            request_ir=request_ir,
            request_curated_raw=request_curated_raw,
            request_curated_ir=request_curated_ir,
            request_audit=request_audit,
            response_raw=response_raw,
            response_ir=response_ir,
            transport=transport,
            events=events,
            turn=turn,
        )

    async def read_codex_derived_files(self, exchange_id: str) -> CodexDerivedArtifactFiles:
        exchange_dir = self._find_exchange_dir(exchange_id)
        paths = self._layout.artifact_paths(exchange_dir)

        events_jsonl: bytes | None = None
        if paths.events.exists():
            events_jsonl = await self._read_bytes(paths.events)

        turn_json: bytes | None = None
        if paths.turn.exists():
            turn_json = await self._read_bytes(paths.turn)

        return CodexDerivedArtifactFiles(
            events_jsonl=events_jsonl,
            turn_json=turn_json,
        )

    async def write_codex_derived_artifacts(
        self, exchange_id: str, artifacts: ExchangeArtifacts
    ) -> None:
        artifacts.validate_codex_derived_artifacts()
        if artifacts.events is None or artifacts.turn is None:
            msg = "Codex derived artifacts require both events and turn"
            raise ValueError(msg)

        final_dir = self._find_exchange_dir(exchange_id)
        tmp_dir = self._layout.tmp_exchange_dir(final_dir)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        try:
            await self._run_io(shutil.copytree, final_dir, tmp_dir)
            paths = self._layout.artifact_paths(tmp_dir)
            await self._write_events_jsonl(paths.events, artifacts.events)
            await self._write_turn_json(paths.turn, artifacts.turn)
            backup_dir = await self._activate_exchange_dir(tmp_dir, final_dir)
            await self._cleanup_exchange_backup(backup_dir)
        except BaseException:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    # ── private helpers ─────────────────────────────────────────────

    def _find_exchange_dir(self, exchange_id: str) -> Path:
        """Locate an exchange directory by its ID prefix."""
        exchange_dir = self._find_exchange_dir_or_none(exchange_id)
        if exchange_dir is not None:
            return exchange_dir
        msg = f"Exchange directory not found for {exchange_id}"
        raise FileNotFoundError(msg)

    def _find_exchange_dir_or_none(self, exchange_id: str) -> Path | None:
        """Locate an exchange directory by its ID prefix, or return None."""
        return self._layout.find_exchange_dir(exchange_id)

    def _prepare_exchange_write(
        self, exchange_id: str, *, now: datetime | None = None
    ) -> tuple[Path, Path]:
        final_dir = self._layout.exchange_dir_for_write(exchange_id, now=now)
        tmp_dir = self._layout.tmp_exchange_dir(final_dir)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return final_dir, tmp_dir

    async def _write_exchange_files(self, tmp_dir: Path, artifacts: ExchangeArtifacts) -> None:
        paths = self._layout.artifact_paths(tmp_dir)
        await self._write_bytes(paths.request_raw, artifacts.request_raw)

        ir_json = artifacts.request_ir.model_dump_json(indent=2)
        await self._write_text(paths.request_ir, ir_json)

        if artifacts.request_curated_raw is not None:
            await self._write_bytes(
                paths.request_curated_raw,
                artifacts.request_curated_raw,
            )

        if artifacts.request_curated_ir is not None:
            curated_json = artifacts.request_curated_ir.model_dump_json(indent=2)
            await self._write_text(
                paths.request_curated_ir,
                curated_json,
            )

        if artifacts.request_audit is not None:
            audit_json = artifacts.request_audit.model_dump_json(indent=2)
            await self._write_text(paths.request_audit, audit_json)

        if artifacts.response_raw is not None:
            await self._write_bytes(paths.response_raw, artifacts.response_raw)

        if artifacts.response_ir is not None:
            resp_json = artifacts.response_ir.model_dump_json(indent=2)
            await self._write_text(paths.response_ir, resp_json)

        if artifacts.transport is not None:
            sanitized_transport, _ = redact_transport_artifacts(artifacts.transport)
            if sanitized_transport is not None:
                await self._write_transport_json(
                    paths.transport,
                    sanitized_transport,
                )

        if artifacts.events is not None:
            await self._write_events_jsonl(paths.events, artifacts.events)

        if artifacts.turn is not None:
            await self._write_turn_json(paths.turn, artifacts.turn)

    async def _write_transport_json(
        self,
        path: Path,
        transport: TransportArtifacts,
    ) -> None:
        transport_json = transport.model_dump_json(indent=2)
        await self._write_text(path, transport_json)

    async def _read_events_jsonl(self, path: Path) -> tuple[CodexSemanticEvent, ...]:
        lines = await self._read_lines(path)
        events: list[CodexSemanticEvent] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            events.append(CodexSemanticEvent.model_validate_json(stripped))
        return tuple(events)

    async def _write_events_jsonl(
        self,
        path: Path,
        events: tuple[CodexSemanticEvent, ...],
    ) -> None:
        await self._write_bytes(path, serialize_codex_events_jsonl(events))

    async def _write_turn_json(
        self,
        path: Path,
        turn: CodexTurnSummary,
    ) -> None:
        durable_turn = self._durable_turn(turn)
        await self._write_bytes(path, serialize_codex_turn_json(durable_turn))

    def _durable_turn(self, turn: CodexTurnSummary) -> CodexTurnSummary:
        if turn.status == "open":
            return turn
        if turn.cursor is None:
            return turn
        return turn.model_copy(update={"cursor": None})
