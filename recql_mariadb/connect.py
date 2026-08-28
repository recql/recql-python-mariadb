"""Open a MariaDB pool + RecQL plugin registry from a DSN."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from recql.catalog import EngineCatalog
from recql.plugins.base import PluginRegistry


async def open_connection(
    dsn: str,
    *,
    catalog: EngineCatalog | None = None,
    minsize: int = 1,
    maxsize: int = 4,
    **kwargs: Any,
) -> tuple[PluginRegistry, Callable[[], Awaitable[None]]]:
    """Return ``(registry, close)`` for ``mariadb://…`` / ``mysql://…`` DSNs."""
    from recql_mariadb import open_registry
    from recql_mariadb.db import create_pool

    pool = await create_pool(dsn, minsize=minsize, maxsize=maxsize)
    registry = await open_registry(catalog=catalog, pool=pool, **kwargs)

    async def close() -> None:
        pool.close()
        await pool.wait_closed()

    return registry, close
