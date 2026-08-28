"""Assemble the MariaDB PluginRegistry (retrievers, scorers, filters, KV)."""

from __future__ import annotations

from typing import Any

from recql.catalog.bindings import DataBindings, bindings_from_catalog, default_fixture_bindings
from recql.encode import get_encoder, warm_encoders_for_catalog
from recql.plugins.base import PluginRegistry
from recql.plugins.mock import MockExpressionFilter, MockScorer
from recql.plugins.sql_common import (
    BoundDbExecutor,
    SqlPrebuiltFilter,
    TemplateCandidateIdsRetriever,
    TemplateColumnOrderRetriever,
    TemplateFilterRetriever,
)
from recql_mariadb.db import MariaDb, fetch_all
from recql_mariadb.kv import MariaDBKvStore
from recql_mariadb.pushdown import assert_pushdown_or_raise, supports_prefilter
from recql_mariadb.retrievers import MariaDBSimilarityRetriever, MariaDBTextSearchRetriever
from recql_mariadb.schema import ensure_operational_tables
from recql_mariadb.scorer import MariaDBModelScorer


def _dims_from_catalog(catalog, *, default: int = 8) -> int:
    if catalog is None:
        return default
    embeddings = getattr(catalog, "embeddings", None) or {}
    for preferred in ("content_embedding", "title_embedding"):
        emb = embeddings.get(preferred)
        if emb is not None and getattr(emb, "dims", None):
            return int(emb.dims)
    for emb in embeddings.values():
        if getattr(emb, "dims", None):
            return int(emb.dims)
    return default


async def mariadb_registry(
    handle,
    *,
    catalog=None,
    plugin_cfg: dict[str, Any] | None = None,
    dims: int | None = None,
    bindings: DataBindings | None = None,
    encode_backend: str | None = None,
    warm_models: bool = True,
    **_kwargs: Any,
) -> PluginRegistry:
    if plugin_cfg is None and catalog is not None:
        from recql.plugins.factory import plugin_config
        plugin_cfg = plugin_config(catalog, "mariadb")
    cfg = dict(plugin_cfg or {})
    db = handle if isinstance(handle, MariaDb) else MariaDb(handle)
    resolved = bindings or (
        bindings_from_catalog(catalog)
        if catalog is not None
        else default_fixture_bindings(backend="mariadb")
    )
    if dims is None:
        dims = _dims_from_catalog(catalog, default=8)
    if encode_backend is None:
        encode_backend = str(cfg.get("encode_backend") or "fake")
    warmed = warm_encoders_for_catalog(catalog, backend=encode_backend, dims=dims)
    encoder = warmed[0] if warmed else get_encoder(backend=encode_backend, dims=dims, warm=True)

    await ensure_operational_tables(db, kv=resolved.pagination_kv)

    ex = BoundDbExecutor(db, fetch_all)
    col = TemplateColumnOrderRetriever(
        ex,
        default_backend="mariadb",
        assert_pushdown=assert_pushdown_or_raise,
        supports_prefilter_fn=supports_prefilter,
    )
    filt = TemplateFilterRetriever(
        ex,
        default_backend="mariadb",
        assert_pushdown=assert_pushdown_or_raise,
        supports_prefilter_fn=supports_prefilter,
        default_where="1=1",
    )
    ids = TemplateCandidateIdsRetriever(
        ex, default_backend="mariadb", supports_prefilter_fn=supports_prefilter
    )
    sim = MariaDBSimilarityRetriever(db, dims=dims, plugin_cfg=cfg)
    text = MariaDBTextSearchRetriever(db, encoder=encoder, plugin_cfg=cfg)
    model_scorer = MariaDBModelScorer(db, catalog=catalog, bindings=resolved)

    registry = PluginRegistry(
        retrievers={
            "column_order": col,
            "filter": filt,
            "candidate_ids": ids,
            "candidate_attributes": filt,
            "text_search": text,
            "similarity": sim,
        },
        scorers={"score_ensemble": model_scorer, "passthrough": MockScorer()},
        reorderers={},
        filters={
            "expression": MockExpressionFilter(),
            "prebuilt": SqlPrebuiltFilter(ex, bindings=resolved, default_backend="mariadb"),
            "truncate": MockExpressionFilter(),
        },
        kv=MariaDBKvStore(db, binding=resolved.pagination_kv),
    )
    registry._recql_bindings = resolved  # type: ignore[attr-defined]
    registry._recql_catalog = catalog  # type: ignore[attr-defined]
    registry._recql_encoder = encoder  # type: ignore[attr-defined]
    registry._recql_plugin_cfg = cfg  # type: ignore[attr-defined]
    registry._recql_model_scorer = model_scorer  # type: ignore[attr-defined]
    registry._recql_db = db  # type: ignore[attr-defined]
    if warm_models and catalog is not None and catalog.models:
        try:
            await model_scorer.warm()
        except Exception:
            pass
    return registry
