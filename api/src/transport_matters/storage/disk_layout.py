"""Internal disk storage layout policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from transport_matters.storage_roots import default_storage_root

_DEFAULT_ROOT = default_storage_root()
_INDEX_FILENAME = "index.jsonl"
_INDEX_TMP_FILENAME = "index.jsonl.tmp"
_ENTRY_FILENAME = "entry.json"
_REQUEST_RAW_FILENAME = "request.raw"
_REQUEST_IR_FILENAME = "request.ir.json"
_REQUEST_CURATED_RAW_FILENAME = "request.curated.raw"
_REQUEST_CURATED_IR_FILENAME = "request.curated.ir.json"
_REQUEST_AUDIT_FILENAME = "request.audit.json"
_RESPONSE_RAW_FILENAME = "response.raw"
_RESPONSE_IR_FILENAME = "response.ir.json"
_TRANSPORT_FILENAME = "transport.json"
_EVENTS_FILENAME = "events.jsonl"
_TURN_FILENAME = "turn.json"
_TMP_SUFFIX = ".tmp"
_BACKUP_SUFFIX = ".bak"
_DELETE_SUFFIX = ".del"
_TS_SLUG_FORMAT = "%Y%m%dT%H%M%SZ"


@dataclass(frozen=True, slots=True)
class ExchangeArtifactPaths:
    directory: Path
    entry: Path
    request_raw: Path
    request_ir: Path
    request_curated_raw: Path
    request_curated_ir: Path
    request_audit: Path
    response_raw: Path
    response_ir: Path
    transport: Path
    events: Path
    turn: Path


class DiskStorageLayout:
    """Path policy for disk backed storage."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else _DEFAULT_ROOT

    @property
    def index_path(self) -> Path:
        return self.root / _INDEX_FILENAME

    @property
    def index_tmp_path(self) -> Path:
        return self.root / _INDEX_TMP_FILENAME

    def artifact_paths(self, exchange_dir: Path) -> ExchangeArtifactPaths:
        return ExchangeArtifactPaths(
            directory=exchange_dir,
            entry=exchange_dir / _ENTRY_FILENAME,
            request_raw=exchange_dir / _REQUEST_RAW_FILENAME,
            request_ir=exchange_dir / _REQUEST_IR_FILENAME,
            request_curated_raw=exchange_dir / _REQUEST_CURATED_RAW_FILENAME,
            request_curated_ir=exchange_dir / _REQUEST_CURATED_IR_FILENAME,
            request_audit=exchange_dir / _REQUEST_AUDIT_FILENAME,
            response_raw=exchange_dir / _RESPONSE_RAW_FILENAME,
            response_ir=exchange_dir / _RESPONSE_IR_FILENAME,
            transport=exchange_dir / _TRANSPORT_FILENAME,
            events=exchange_dir / _EVENTS_FILENAME,
            turn=exchange_dir / _TURN_FILENAME,
        )

    def new_exchange_dir(
        self, exchange_id: str, *, now: datetime | None = None
    ) -> Path:
        ts = now or datetime.now(tz=UTC)
        return self.root / self.exchange_dir_name(exchange_id, ts=ts)

    def exchange_dir_name(self, exchange_id: str, *, ts: datetime) -> str:
        return f"{ts.strftime(_TS_SLUG_FORMAT)}-{self.short_id(exchange_id)}"

    def find_exchange_dir(self, exchange_id: str) -> Path | None:
        suffix = f"-{self.short_id(exchange_id)}"
        for exchange_dir in self.root.iterdir():
            if exchange_dir.is_dir() and exchange_dir.name.endswith(suffix):
                return exchange_dir
        return None

    def exchange_dir_for_write(
        self, exchange_id: str, *, now: datetime | None = None
    ) -> Path:
        return self.find_exchange_dir(exchange_id) or self.new_exchange_dir(
            exchange_id,
            now=now,
        )

    def tmp_exchange_dir(self, final_dir: Path) -> Path:
        return final_dir.parent / f"{final_dir.name}{_TMP_SUFFIX}"

    def backup_exchange_dir(self, final_dir: Path) -> Path:
        return final_dir.parent / f"{final_dir.name}{_BACKUP_SUFFIX}"

    def staged_delete_dir(self, final_dir: Path) -> Path:
        return final_dir.parent / f"{final_dir.name}{_DELETE_SUFFIX}"

    def live_dir_for_backup(self, backup_dir: Path) -> Path:
        return backup_dir.with_name(backup_dir.name.removesuffix(_BACKUP_SUFFIX))

    def live_dir_for_staged_delete(self, staged_dir: Path) -> Path:
        return staged_dir.with_name(staged_dir.name.removesuffix(_DELETE_SUFFIX))

    def exchange_index_path(self, exchange_dir_name: str) -> str:
        return f"exchanges/{exchange_dir_name}/"

    def exchange_index_path_for(self, exchange_id: str, *, ts: datetime) -> str:
        return self.exchange_index_path(self.exchange_dir_name(exchange_id, ts=ts))

    def should_recover_exchange_dir(self, exchange_dir: Path) -> bool:
        return (
            exchange_dir.is_dir()
            and not self.is_tmp_exchange_dir(exchange_dir)
            and not self.is_backup_exchange_dir(exchange_dir)
            and not self.is_staged_delete_dir(exchange_dir)
        )

    def is_tmp_exchange_dir(self, exchange_dir: Path) -> bool:
        return exchange_dir.is_dir() and exchange_dir.name.endswith(_TMP_SUFFIX)

    def is_backup_exchange_dir(self, exchange_dir: Path) -> bool:
        return exchange_dir.is_dir() and exchange_dir.name.endswith(_BACKUP_SUFFIX)

    def is_staged_delete_dir(self, exchange_dir: Path) -> bool:
        return exchange_dir.is_dir() and exchange_dir.name.endswith(_DELETE_SUFFIX)

    def exchange_timestamp(self, exchange_dir: Path) -> datetime:
        prefix, _, _ = exchange_dir.name.rpartition("-")
        if prefix:
            try:
                return datetime.strptime(prefix, _TS_SLUG_FORMAT).replace(tzinfo=UTC)
            except ValueError:
                pass
        return datetime.fromtimestamp(exchange_dir.stat().st_mtime, tz=UTC)

    def matches_exchange_id(self, exchange_dir: Path, exchange_id: str) -> bool:
        return exchange_dir.name.endswith(f"-{self.short_id(exchange_id)}")

    def short_id(self, exchange_id: str) -> str:
        return exchange_id[:8]

    def short_id_from_dir_name(self, exchange_dir_name: str) -> str:
        return exchange_dir_name.rsplit("-", 1)[-1]
