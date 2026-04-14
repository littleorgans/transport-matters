"""Disk-backed storage backend.

Persists exchange artifacts and index to ``~/.manicure/exchanges/``
(configurable).  Uses ``aiofiles`` for non-blocking file I/O.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import aiofiles

from manicure.ir import InternalRequest, InternalResponse
from manicure.storage.base import (
    ExchangeArtifacts,
    IndexEntry,
    StorageBackend,
)

logger = logging.getLogger(__name__)

_DEFAULT_ROOT = Path.home() / ".manicure" / "exchanges"


class DiskStorageBackend(StorageBackend):
    """Append-only JSONL index with per-exchange artifact directories."""

    def __init__(self, root: str | Path | None = None) -> None:
        self._root = Path(root) if root else _DEFAULT_ROOT
        self._root.mkdir(parents=True, exist_ok=True)
        self._index_lock = asyncio.Lock()
        self._index_cache: dict[str, IndexEntry] | None = None
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
            async with aiofiles.open(index_path) as f:
                lines = await f.readlines()
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
        self._index_cache = entries
        return entries

    async def append_index(self, entry: IndexEntry) -> None:
        index_path = self._root / "index.jsonl"
        line = entry.model_dump_json() + "\n"
        async with self._index_lock:
            async with aiofiles.open(index_path, mode="a") as f:
                await f.write(line)
            if self._index_cache is not None:
                self._index_cache[entry.id] = entry

    async def read_index(self, limit: int, offset: int) -> list[IndexEntry]:
        async with self._index_lock:
            cache = await self._ensure_index_cache()
        entries = list(cache.values())
        return entries[offset : offset + limit]

    async def read_index_entry(self, exchange_id: str) -> IndexEntry | None:
        async with self._index_lock:
            cache = await self._ensure_index_cache()
            return cache.get(exchange_id)

    # ── exchange artifacts ──────────────────────────────────────────

    async def write_exchange(
        self, exchange_id: str, artifacts: ExchangeArtifacts
    ) -> None:
        final_dir = self._exchange_dir(exchange_id, artifacts)
        tmp_dir = final_dir.parent / f"{final_dir.name}.tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        try:
            async with aiofiles.open(tmp_dir / "request.raw", mode="wb") as f:
                await f.write(artifacts.request_raw)

            ir_json = artifacts.request_ir.model_dump_json(indent=2)
            async with aiofiles.open(tmp_dir / "request.ir.json", mode="w") as f:
                await f.write(ir_json)

            if artifacts.request_curated_ir is not None:
                curated_json = artifacts.request_curated_ir.model_dump_json(indent=2)
                async with aiofiles.open(
                    tmp_dir / "request.curated.ir.json", mode="w"
                ) as f:
                    await f.write(curated_json)

            if artifacts.response_raw is not None:
                async with aiofiles.open(tmp_dir / "response.raw", mode="wb") as f:
                    await f.write(artifacts.response_raw)

            if artifacts.response_ir is not None:
                resp_json = artifacts.response_ir.model_dump_json(indent=2)
                async with aiofiles.open(tmp_dir / "response.ir.json", mode="w") as f:
                    await f.write(resp_json)

            tmp_dir.rename(final_dir)
        except BaseException:
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    async def read_exchange(self, exchange_id: str) -> ExchangeArtifacts:
        exchange_dir = self._find_exchange_dir(exchange_id)

        async with aiofiles.open(exchange_dir / "request.raw", mode="rb") as f:
            request_raw = await f.read()

        async with aiofiles.open(exchange_dir / "request.ir.json") as f:
            request_ir_json = await f.read()
        request_ir = InternalRequest.model_validate_json(request_ir_json)

        curated_path = exchange_dir / "request.curated.ir.json"
        request_curated_ir: InternalRequest | None = None
        if curated_path.exists():
            async with aiofiles.open(curated_path) as f:
                curated_json = await f.read()
            request_curated_ir = InternalRequest.model_validate_json(curated_json)

        response_raw: bytes | None = None
        resp_raw_path = exchange_dir / "response.raw"
        if resp_raw_path.exists():
            async with aiofiles.open(resp_raw_path, mode="rb") as f:
                response_raw = await f.read()

        response_ir: InternalResponse | None = None
        resp_ir_path = exchange_dir / "response.ir.json"
        if resp_ir_path.exists():
            async with aiofiles.open(resp_ir_path) as f:
                resp_ir_json = await f.read()
            response_ir = InternalResponse.model_validate_json(resp_ir_json)

        return ExchangeArtifacts(
            request_raw=request_raw,
            request_ir=request_ir,
            request_curated_ir=request_curated_ir,
            response_raw=response_raw,
            response_ir=response_ir,
        )

    # ── private helpers ─────────────────────────────────────────────

    def _exchange_dir(self, exchange_id: str, artifacts: ExchangeArtifacts) -> Path:
        """Build the per-exchange directory path: ``{ts_slug}-{id[:8]}/``."""
        ts = datetime.now(tz=UTC)
        ts_slug = ts.strftime("%Y%m%dT%H%M%SZ")
        return self._root / f"{ts_slug}-{exchange_id[:8]}"

    def _find_exchange_dir(self, exchange_id: str) -> Path:
        """Locate an exchange directory by its ID prefix."""
        short = exchange_id[:8]
        for d in self._root.iterdir():
            if d.is_dir() and d.name.endswith(f"-{short}"):
                return d
        msg = f"Exchange directory not found for {exchange_id}"
        raise FileNotFoundError(msg)

    def _cleanup_partial_writes(self) -> None:
        """Remove leftover ``.tmp`` directories from interrupted writes."""
        import shutil

        if not self._root.exists():
            return
        for d in self._root.iterdir():
            if d.is_dir() and d.name.endswith(".tmp"):
                logger.warning("Cleaning up partial write: %s", d)
                shutil.rmtree(d, ignore_errors=True)
