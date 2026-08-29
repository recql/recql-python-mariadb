"""MariaDB pagination KV."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from recql.catalog.bindings import PaginationKvBinding
from recql.plugins.base import KvStore
from recql_mariadb.db import MariaDb, execute, fetch_all
from recql_mariadb.schema import ensure_operational_tables


class MariaDBKvStore(KvStore):
    def __init__(self, db: Any, *, binding: PaginationKvBinding | None = None) -> None:
        self.db = db if isinstance(db, MariaDb) else MariaDb(db)
        self.binding = binding or PaginationKvBinding()
        self._ensured = False

    async def _ensure(self) -> None:
        if self._ensured:
            return
        await ensure_operational_tables(self.db, kv=self.binding)
        self._ensured = True

    async def load_seen(self, key: str) -> set[str]:
        await self._ensure()
        b = self.binding
        rows = await fetch_all(
            self.db,
            f"""
            SELECT `{b.item_id_column}` AS item_id FROM `{b.from_sql}`
            WHERE `{b.key_column}` = %s AND `{b.expires_at_column}` > CURRENT_TIMESTAMP(6)
            """,
            [key],
        )
        return {str(r["item_id"]) for r in rows}

    async def remember(self, key: str, ids: list[str], ttl: int) -> None:
        if not ids:
            return
        await self._ensure()
        b = self.binding
        expires = datetime.now(timezone.utc) + timedelta(seconds=int(ttl))
        for iid in ids:
            await execute(
                self.db,
                f"""
                INSERT INTO `{b.from_sql}`
                  (`{b.key_column}`, `{b.item_id_column}`, `{b.expires_at_column}`)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE `{b.expires_at_column}` = VALUES(`{b.expires_at_column}`)
                """,
                [key, iid, expires],
            )
