"""MariaDB 11.7+ plugin pack — VECTOR + FULLTEXT + KV + pushdown.

Configured via engine YAML ``plugins.backend: mariadb``.
Demo stack: ``examples/generator/mariadb/``.
"""

from __future__ import annotations

from typing import Any

from recql.plugins.base import PluginRegistry
from recql_mariadb import dialect as _dialect  # noqa: F401 — register SQL dialect
from recql_mariadb.registry import mariadb_registry
from recql_mariadb.schema import ensure_operational_tables

__all__ = [
    "ensure_operational_tables",
    "mariadb_registry",
    "open_registry",
]


async def open_registry(
    *,
    catalog=None,
    pool=None,
    connection=None,
    plugin_cfg: dict[str, Any] | None = None,
    **kwargs: Any,
) -> PluginRegistry:
    """Entry-point adapter for ``recql.backends`` (called by core factory)."""
    handle = pool or connection
    if handle is None:
        raise ValueError("mariadb backend requires pool= or connection=")
    return await mariadb_registry(
        handle, catalog=catalog, plugin_cfg=plugin_cfg, **kwargs
    )
