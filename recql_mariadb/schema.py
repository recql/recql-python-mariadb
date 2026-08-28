"""MariaDB operational tables from ``PaginationKvBinding``."""

from __future__ import annotations

from typing import Any

from recql.catalog.bindings import PaginationKvBinding
from recql_mariadb.db import MariaDb, execute


def pagination_seen_ddl(kv: PaginationKvBinding | None = None) -> str:
    b = kv or PaginationKvBinding()
    return f"""
CREATE TABLE IF NOT EXISTS {b.from_sql} (
  {b.key_column} VARCHAR(512) NOT NULL,
  {b.item_id_column} VARCHAR(128) NOT NULL,
  {b.expires_at_column} TIMESTAMP(6) NOT NULL,
  PRIMARY KEY ({b.key_column}, {b.item_id_column})
)
"""


ARTIFACT_REGISTRY_DDL = """
CREATE TABLE IF NOT EXISTS artifact_registry (
  kind VARCHAR(32) NOT NULL,
  name VARCHAR(128) NOT NULL,
  version VARCHAR(64) NOT NULL,
  dims INT,
  config_hash VARCHAR(64),
  feature_spec JSON,
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (kind, name, version)
)
"""


async def ensure_operational_tables(db: Any, *, kv: PaginationKvBinding | None = None) -> None:
    handle = db if isinstance(db, MariaDb) else MariaDb(db)
    binding = kv or PaginationKvBinding()
    if binding.ensure_table:
        await execute(handle, pagination_seen_ddl(binding))
    await execute(handle, ARTIFACT_REGISTRY_DDL)
