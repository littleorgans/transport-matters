from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from typing import TYPE_CHECKING

from psycopg import AsyncConnection, Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool, ConnectionPool

from transport_matters.config import Settings, get_settings, resolve_database_url

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator


def sqlalchemy_url(database_url: str) -> str:
    if database_url.startswith("postgresql+psycopg://"):
        return database_url
    if database_url.startswith("postgres://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgres://")
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    return database_url


def connect(database_url: str | None = None, *, autocommit: bool = False) -> Connection[DictRow]:
    return Connection.connect(
        _resolved_url(database_url),
        autocommit=autocommit,
        row_factory=dict_row,
    )


async def async_connect(
    database_url: str | None = None, *, autocommit: bool = False
) -> AsyncConnection[DictRow]:
    return await AsyncConnection.connect(
        _resolved_url(database_url),
        autocommit=autocommit,
        row_factory=dict_row,
    )


def create_pool(
    database_url: str | None = None,
    *,
    min_size: int | None = None,
    max_size: int | None = None,
) -> ConnectionPool[Connection[DictRow]]:
    settings = get_settings()
    return ConnectionPool(
        _resolved_url(database_url, settings),
        min_size=min_size if min_size is not None else settings.session_pool_min_size,
        max_size=max_size if max_size is not None else settings.session_pool_max_size,
        kwargs={"row_factory": dict_row},
        open=False,
    )


def create_async_pool(
    database_url: str | None = None,
    *,
    min_size: int | None = None,
    max_size: int | None = None,
) -> AsyncConnectionPool[AsyncConnection[DictRow]]:
    settings = get_settings()
    return AsyncConnectionPool(
        _resolved_url(database_url, settings),
        min_size=min_size if min_size is not None else settings.session_pool_min_size,
        max_size=max_size if max_size is not None else settings.session_pool_max_size,
        kwargs={"row_factory": dict_row},
        open=False,
    )


@contextmanager
def transaction(conn: Connection[DictRow]) -> Iterator[Connection[DictRow]]:
    with conn.transaction():
        yield conn


@asynccontextmanager
async def async_transaction(
    conn: AsyncConnection[DictRow],
) -> AsyncIterator[AsyncConnection[DictRow]]:
    async with conn.transaction():
        yield conn


def _resolved_url(database_url: str | None, settings: Settings | None = None) -> str:
    if database_url is not None:
        return database_url
    return resolve_database_url(settings if settings is not None else get_settings())
