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
from typing import Any  # Any: opaque rule definitions

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

    @property
    def root(self) -> Path:
        return self._root

    # ── index ───────────────────────────────────────────────────────

    async def append_index(self, entry: IndexEntry) -> None:
        index_path = self._root / "index.jsonl"
        line = entry.model_dump_json() + "\n"
        async with self._index_lock, aiofiles.open(index_path, mode="a") as f:
            await f.write(line)

    async def read_index(self, limit: int, offset: int) -> list[IndexEntry]:
        index_path = self._root / "index.jsonl"
        if not index_path.exists():
            return []
        async with aiofiles.open(index_path) as f:
            lines = await f.readlines()
        entries: list[IndexEntry] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # A line may contain multiple concatenated JSON objects due to a past
            # concurrent-write bug. Extract all valid objects from the line.
            pos = 0
            decoder = json.JSONDecoder()
            while pos < len(line):
                try:
                    obj, end = decoder.raw_decode(line, pos)
                    entries.append(IndexEntry.model_validate(obj))
                    pos = end
                except (json.JSONDecodeError, Exception) as exc:
                    logger.warning(
                        "Skipping malformed index entry at pos %d: %s", pos, exc
                    )
                    break
        return entries[offset : offset + limit]

    # ── exchange artifacts ──────────────────────────────────────────

    async def write_exchange(
        self, exchange_id: str, artifacts: ExchangeArtifacts
    ) -> None:
        exchange_dir = self._exchange_dir(exchange_id, artifacts)
        exchange_dir.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(exchange_dir / "request.raw", mode="wb") as f:
            await f.write(artifacts.request_raw)

        ir_json = artifacts.request_ir.model_dump_json(indent=2)
        async with aiofiles.open(exchange_dir / "request.ir.json", mode="w") as f:
            await f.write(ir_json)

        if artifacts.request_curated_ir is not None:
            curated_json = artifacts.request_curated_ir.model_dump_json(indent=2)
            async with aiofiles.open(
                exchange_dir / "request.curated.ir.json", mode="w"
            ) as f:
                await f.write(curated_json)

        if artifacts.response_raw is not None:
            async with aiofiles.open(exchange_dir / "response.raw", mode="wb") as f:
                await f.write(artifacts.response_raw)

        if artifacts.response_ir is not None:
            resp_json = artifacts.response_ir.model_dump_json(indent=2)
            async with aiofiles.open(exchange_dir / "response.ir.json", mode="w") as f:
                await f.write(resp_json)

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

    # ── rules ───────────────────────────────────────────────────────

    async def load_rules(self) -> list[dict[str, Any]]:  # Any: opaque rule defs
        rules_path = self._root / "rules.json"
        if not rules_path.exists():
            return []
        async with aiofiles.open(rules_path) as f:
            content = await f.read()
        result: list[dict[str, Any]] = json.loads(content)  # Any: opaque rule defs
        return result

    async def save_rules(
        self,
        rules: list[dict[str, Any]],  # Any: opaque rule defs
    ) -> None:
        rules_path = self._root / "rules.json"
        async with aiofiles.open(rules_path, mode="w") as f:
            await f.write(json.dumps(rules, indent=2))

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
