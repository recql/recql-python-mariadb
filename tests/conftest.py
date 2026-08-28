"""MariaDB testbed — seeds demo data, exposes ``recql_testbed`` for core suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from recql.catalog import load_engine_catalog
from recql.testing import RecqlTestbed, SQL_BACKEND_FEATURES


from recql_mariadb.db import create_pool

DSN = os.environ.get(
    "RECQL_MARIADB_DSN",
    "mariadb://recql:recql@127.0.0.1:3307/recql",
)


def _resolve_engine() -> Path:
    if os.environ.get("RECQL_ENGINE"):
        return Path(os.environ["RECQL_ENGINE"])
    local = Path(__file__).resolve().parents[1] / "testdata" / "engine.yaml"
    if local.is_file():
        return local
    pytest.skip("engine.yaml not found — set RECQL_ENGINE")


@pytest.fixture(scope="session")
async def recql_testbed():
    try:
        from examples.generator.catalog import build_demo_catalog
        from examples.generator.mariadb.load import load_catalog
    except ImportError:
        pytest.skip("recql-playground required for seeding")

    try:
        pool = await create_pool(DSN, minsize=1, maxsize=4)
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
    except Exception:
        pytest.skip("MariaDB unavailable — run `make up` in this repo")
        return

    catalog_demo = build_demo_catalog(
        dims=8,
        with_als=True,
        with_lgbm=True,
        max_movies=100,
        max_ratings=4000,
        als_max_users=50,
        als_max_items=150,
        als_steps=5,
    )
    async with pool.acquire() as conn:
        await load_catalog(conn, catalog_demo)

    catalog = load_engine_catalog(_resolve_engine())
    from recql_mariadb import open_registry

    registry = await open_registry(catalog=catalog, pool=pool)

    async def closer():
        pool.close()
        await pool.wait_closed()

    bed = RecqlTestbed(
        backend="mariadb",
        registry=registry,
        catalog=catalog,
        dims=8,
        popular_rank_column="derived_popular_rank",
        features=SQL_BACKEND_FEATURES,
    )
    yield bed
    await closer()
