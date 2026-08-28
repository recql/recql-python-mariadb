"""Shared MariaDB connection handle — aiomysql pool with DictCursor."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from urllib.parse import unquote, urlparse


class MariaDb:
    def __init__(self, pool: Any) -> None:
        self.pool = pool
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[Any]:
        async with self.pool.acquire() as conn:
            yield conn


async def fetch_all(db: MariaDb, sql: str, binds: list[Any] | None = None) -> list[dict[str, Any]]:
    import aiomysql

    async with db.connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, binds or [])
            rows = await cur.fetchall()
            return [dict(r) for r in (rows or [])]


async def fetch_one(db: MariaDb, sql: str, binds: list[Any] | None = None) -> dict[str, Any] | None:
    rows = await fetch_all(db, sql, binds)
    return rows[0] if rows else None


async def execute(
    db: MariaDb, sql: str, binds: list[Any] | None = None, *, commit: bool = True
) -> None:
    async with db.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, binds or [])
        if commit:
            await conn.commit()


def parse_mariadb_dsn(dsn: str) -> dict[str, Any]:
    """Parse ``mariadb://user:pass@host:3306/db`` or ``mysql://…`` into aiomysql kwargs."""
    raw = dsn
    for prefix in ("mariadb://", "mysql://", "maria://"):
        if raw.lower().startswith(prefix):
            raw = "mysql://" + raw[len(prefix) :]
            break
    if "://" not in raw:
        raw = "mysql://" + raw
    parsed = urlparse(raw)
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": int(parsed.port or 3306),
        "user": unquote(parsed.username or "recql"),
        "password": unquote(parsed.password or "recql"),
        "db": (parsed.path or "/recql").lstrip("/") or "recql",
        "autocommit": True,
    }


def vec_literal(vector: list[float] | Any) -> str:
    """MariaDB ``VEC_FromText`` payload: ``[0.1,0.2,…]``."""
    if isinstance(vector, str):
        return vector
    vals = list(vector)
    return "[" + ",".join(str(float(x)) for x in vals) + "]"


def quote_ident(name: str) -> str:
    """Backtick-quote an identifier (``blob``, ``key``, etc. are reserved)."""
    return "`" + str(name).replace("`", "``") + "`"


async def create_pool(dsn: str, *, minsize: int = 1, maxsize: int = 4):
    import aiomysql

    kwargs = parse_mariadb_dsn(dsn)
    return await aiomysql.create_pool(minsize=minsize, maxsize=maxsize, **kwargs)
