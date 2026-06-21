from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import core_schema

if TYPE_CHECKING:
    from collections.abc import Callable

MIN_SHORT_PREFIX_LEN = 7
JsonObject = dict[str, Any]  # Any is necessary for arbitrary jsonb layout payloads.


def shortest_unambiguous_prefix(full_id: str, is_unique: Callable[[str], bool]) -> str:
    min_len = min(MIN_SHORT_PREFIX_LEN, len(full_id))
    for length in range(min_len, len(full_id) + 1):
        candidate = full_id[:length]
        if is_unique(candidate):
            return candidate
    return full_id


class _UuidId:
    __slots__ = ("_value",)

    def __init__(self, value: UUID) -> None:
        self._value = value

    @classmethod
    def new(cls) -> Self:
        return cls(uuid4())

    @classmethod
    def from_uuid(cls, value: UUID) -> Self:
        return cls(value)

    @classmethod
    def parse(cls, value: str) -> Self:
        return cls(UUID(value))

    def as_uuid(self) -> UUID:
        return self._value

    def into_uuid(self) -> UUID:
        return self._value

    def short(self, is_unique: Callable[[str], bool] | None = None) -> str:
        return shortest_unambiguous_prefix(str(self), is_unique or (lambda _: True))

    def short_with(self, is_unique: Callable[[str], bool]) -> str:
        return self.short(is_unique)

    def __str__(self) -> str:
        return str(self._value)

    def __repr__(self) -> str:
        return f"{type(self).__name__}('{self}')"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, _UuidId) and type(self) is type(other) and self._value == other._value
        )

    def __hash__(self) -> int:
        return hash((type(self), self._value))

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source: type[Any],  # Any is necessary for pydantic-core hook signatures.
        _handler: Any,  # Any is necessary for pydantic-core hook signatures.
    ) -> core_schema.CoreSchema:
        def validate(value: object) -> _UuidId:
            if isinstance(value, cls):
                return value
            if isinstance(value, UUID):
                return cls.from_uuid(value)
            if isinstance(value, str):
                return cls.parse(value)
            raise ValueError(f"{cls.__name__} must be a UUID or UUID string")

        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda value: str(value),
                return_schema=core_schema.str_schema(),
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        _schema: core_schema.CoreSchema,
        _handler: Any,  # Any is necessary for pydantic-core hook signatures.
    ) -> dict[str, Any]:  # Any is necessary for pydantic-core JSON schema maps.
        return {"type": "string", "format": "uuid"}


class _IdentityHashMixin:
    _identity_field: ClassVar[str]

    def __hash__(self) -> int:
        return hash(getattr(self, self._identity_field))


class SpaceId(_UuidId):
    pass


class WorktreeId(_UuidId):
    pass


class CanvasId(_UuidId):
    pass


class Space(_IdentityHashMixin, BaseModel):
    _identity_field: ClassVar[str] = "space_id"
    model_config = ConfigDict(frozen=True)

    space_id: SpaceId
    owner: str = "local"
    name: str
    archived: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SpaceGitIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    space_id: SpaceId
    repo_instance_key: str
    git_common_dir: str
    detected_at: datetime | None = None


class Worktree(_IdentityHashMixin, BaseModel):
    _identity_field: ClassVar[str] = "worktree_id"
    model_config = ConfigDict(frozen=True)

    worktree_id: WorktreeId
    space_id: SpaceId
    owner: str = "local"
    path: str | None = None
    workspace_slug: str
    workspace_hash: str
    branch_name: str | None = None
    head_oid: str | None = None
    is_primary: bool = False
    missing: bool = False
    archived: bool = False
    detected_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Canvas(_IdentityHashMixin, BaseModel):
    _identity_field: ClassVar[str] = "canvas_id"
    model_config = ConfigDict(frozen=True)

    canvas_id: CanvasId
    space_id: SpaceId
    owner: str = "local"
    name: str
    default_worktree_id: WorktreeId | None = None
    layout: JsonObject = Field(default_factory=dict)
    layout_version: int = 1
    archived: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ResolvedWorktree(BaseModel):
    model_config = ConfigDict(frozen=True)

    space_id: SpaceId
    worktree_id: WorktreeId
    cwd: str
    workspace_slug: str
    workspace_hash: str
    missing: bool
    archived: bool
