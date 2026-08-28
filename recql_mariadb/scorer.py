"""MariaDB model scorer — load BLOB once, predict on hot path."""

from __future__ import annotations

import json
from typing import Any

from recql.artifacts import (
    check_feature_spec_compat,
    pins_from_deployment,
    resolve_version,
)
from recql.catalog.bindings import DataBindings, default_fixture_bindings
from recql.errors import ExecuteError
from recql.execute.merge import Candidate
from recql.expr import ExpressionScorer
from recql.plugins.base import Scorer
from recql_mariadb.db import MariaDb, fetch_one, quote_ident
from recql.scoring import load_lgbm_booster, predict_lgbm, click_through_rate_features


class LoadedModel:
    __slots__ = ("name", "version", "booster", "feature_spec")

    def __init__(self, *, name: str, version: str, booster: Any, feature_spec: dict) -> None:
        self.name = name
        self.version = version
        self.booster = booster
        self.feature_spec = feature_spec


class MariaDBModelScorer(Scorer):
    def __init__(self, db: Any, *, catalog=None, bindings: DataBindings | None = None) -> None:
        self.db = db if isinstance(db, MariaDb) else MariaDb(db)
        self.catalog = catalog
        self.bindings = bindings or (
            catalog.bindings() if catalog is not None else default_fixture_bindings(backend="mariadb")
        )
        self._expr = ExpressionScorer()
        self._loaded: dict[tuple[str, str], LoadedModel] = {}

    def _pinned_version(self, name: str) -> str:
        pins = pins_from_deployment(
            self.catalog.deployment if self.catalog is not None else None
        )
        return resolve_version(name, pins, fallback="v1")

    async def warm(self, names: list[str] | None = None) -> list[str]:
        if names is None:
            names = list(self.catalog.models.keys()) if self.catalog is not None else []
        out = []
        for name in names:
            version = self._pinned_version(name)
            await self._ensure_loaded(name, version)
            out.append(f"{name}@{version}")
        return out

    async def _ensure_loaded(self, name: str, version: str) -> LoadedModel:
        key = (name, version)
        if key in self._loaded:
            return self._loaded[key]
        store = self.bindings.models
        blob_col = quote_ident(store.blob_column)
        spec_col = quote_ident(store.feature_spec_column)
        name_col = quote_ident(store.name_column)
        # Alias ``blob`` must be quoted — BLOB is a reserved type name in MariaDB.
        blob_as = quote_ident("blob")
        spec_as = quote_ident("feature_spec")
        ver_as = quote_ident("version")
        ver_col = quote_ident("version")
        row = await fetch_one(
            self.db,
            f"""
            SELECT {blob_col} AS {blob_as},
                   {spec_col} AS {spec_as},
                   {ver_col} AS {ver_as}
            FROM {store.from_sql}
            WHERE {name_col} = %s AND {ver_col} = %s
            LIMIT 1
            """,
            [name, version],
        )
        if row is None:
            row = await fetch_one(
                self.db,
                f"""
                SELECT {blob_col} AS {blob_as},
                       {spec_col} AS {spec_as},
                       {ver_col} AS {ver_as}
                FROM {store.from_sql}
                WHERE {name_col} = %s
                ORDER BY {quote_ident("created_at")} DESC
                LIMIT 1
                """,
                [name],
            )
        if row is None or row.get("blob") is None:
            raise ExecuteError(f"missing ranking model artifact: {name} version={version}")
        found_ver = str(row["version"])
        if found_ver != version:
            raise ExecuteError(
                f"model version pin mismatch for {name}: wanted {version}, found {found_ver}"
            )
        spec = row.get("feature_spec") or {}
        if isinstance(spec, (bytes, bytearray)):
            spec = spec.decode("utf-8")
        if isinstance(spec, str):
            spec = json.loads(spec)
        blob = row["blob"]
        if hasattr(blob, "read"):
            blob = blob.read()
        booster = load_lgbm_booster(bytes(blob))
        loaded = LoadedModel(
            name=name,
            version=version,
            booster=booster,
            feature_spec=dict(spec or {}),
        )
        self._loaded[key] = loaded
        return loaded

    async def score_many(
        self, plan: Any, candidates: list[Candidate], ctx: dict[str, Any]
    ) -> list[float]:
        vm = getattr(plan, "value_model", None) or ""
        if vm and all(c.isalnum() or c == "_" for c in vm):
            version = self._pinned_version(vm)
            model = await self._ensure_loaded(vm, version)
            expected = None
            if self.catalog is not None:
                m = self.catalog.model(vm)
                if m is not None:
                    expected = (m.raw or {}).get("feature_spec")
            check_feature_spec_compat(expected, model.feature_spec)
            feats = [click_through_rate_features(c) for c in candidates]
            return predict_lgbm(model.booster, feats)
        return await self._expr.score_many(plan, candidates, ctx)
