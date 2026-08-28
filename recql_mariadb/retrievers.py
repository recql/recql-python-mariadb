"""MariaDB retrievers — similarity/text stay here; template CRUD in sql_common."""

from __future__ import annotations

import json
from typing import Any

from recql.catalog.bindings import DataBindings
from recql.catalog.query_templates import QueryRenderer
from recql.encode import encode_query
from recql.errors import ExecuteError
from recql.execute.merge import Candidate, RetrieveBag
from recql.language import ast as A
from recql.plugins.base import RetrieveRequest, Retriever
from recql_mariadb.db import MariaDb, fetch_all, fetch_one, vec_literal
from recql_mariadb.pushdown import assert_pushdown_or_raise, supports_prefilter
from recql.plugins.sql_common import (
    attrs_dict,
    bindings_for_request,
    resolve_param,
)

_attrs = attrs_dict
_resolve_param = resolve_param


def _bindings(req: RetrieveRequest) -> DataBindings:
    return bindings_for_request(req, default_backend="mariadb")


def _db(handle: Any) -> MariaDb:
    return handle if isinstance(handle, MariaDb) else MariaDb(handle)


def _parse_embedding(value: Any) -> list[float]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [float(x) for x in value]
    if isinstance(value, (bytes, bytearray)):
        try:
            import struct

            n = len(value) // 4
            return list(struct.unpack(f"<{n}f", bytes(value)[: n * 4]))
        except Exception:
            value = value.decode("utf-8", errors="ignore")
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("["):
            return [float(x) for x in json.loads(s)]
        return [float(x) for x in s.split(",") if x.strip()]
    if hasattr(value, "tolist"):
        return [float(x) for x in value.tolist()]
    return [float(x) for x in value]


class MariaDBSimilarityRetriever(Retriever):
    def __init__(self, db: Any, *, dims: int = 8, plugin_cfg: dict[str, Any] | None = None) -> None:
        self.db = _db(db)
        self.dims = dims
        self.plugin_cfg = plugin_cfg or {}

    def supports_prefilter(self, expr: A.Expr | str | None) -> bool:
        return supports_prefilter("similarity", expr)

    async def retrieve(self, req: RetrieveRequest) -> RetrieveBag:
        step = req.step
        name = getattr(step, "name", None) or "similarity"
        limit = int(getattr(step, "limit", 100) or 100)
        where = getattr(step, "where", None)
        if where is not None:
            assert_pushdown_or_raise("similarity", where)
        bindings = _bindings(req)
        renderer = QueryRenderer(bindings)
        items = bindings.entity(req.entity_type)
        emb_ref = getattr(step, "embedding_ref", None) or "als"
        enc = getattr(step, "query_encoder", None)
        etype = getattr(enc, "type", None) if enc is not None else None

        qvec: str | None = None
        if etype == "precomputed_user":
            uid = str(_resolve_param(enc.input_user_id, req.params or {}))
            emb = bindings.embedding_store_for(str(emb_ref), "user")
            emb_name = str(emb_ref) if emb.name_column else None
            lookup_structural, lookup_binds = renderer.embedding_structural(
                emb,
                embedding_name=emb_name,
                entity_type="user" if emb.entity_type_column else None,
            )
            sql, args = renderer.render(
                "embedding_lookup",
                structural=lookup_structural,
                binds={"entity_id": uid, **lookup_binds},
                store=emb,
            )
            row = await fetch_one(self.db, sql, args)
            if row is None:
                return RetrieveBag(name=str(name), candidates=[])
            qvec = vec_literal(_parse_embedding(row["embedding"]))
        elif etype == "precomputed_item":
            iid = str(_resolve_param(enc.input_item_id, req.params or {}))
            emb = bindings.embedding_store_for(str(emb_ref), "item")
            emb_name = str(emb_ref) if emb.name_column else None
            lookup_structural, lookup_binds = renderer.embedding_structural(
                emb,
                embedding_name=emb_name,
                entity_type="item" if emb.entity_type_column else None,
            )
            sql, args = renderer.render(
                "embedding_lookup",
                structural=lookup_structural,
                binds={"entity_id": iid, **lookup_binds},
                store=emb,
            )
            row = await fetch_one(self.db, sql, args)
            if row is None:
                return RetrieveBag(name=str(name), candidates=[])
            qvec = vec_literal(_parse_embedding(row["embedding"]))
        else:
            raise ExecuteError(f"encoder type {etype} not implemented yet")

        search_emb = bindings.embedding_store_for(str(emb_ref), req.entity_type)
        search_name = str(emb_ref) if search_emb.name_column else None
        search_structural, search_binds = renderer.embedding_structural(
            search_emb,
            embedding_name=search_name,
            entity_type=req.entity_type if search_emb.entity_type_column else None,
        )
        sql, args = renderer.render(
            "embedding_similarity_search",
            structural={**renderer.entity_structural(items), **search_structural},
            binds={"query_vector": qvec, "limit": limit, **search_binds},
            store=search_emb,
        )
        rows = await fetch_all(self.db, sql, args)
        return RetrieveBag(
            name=str(name),
            candidates=[
                Candidate(
                    id=str(r["entity_id"]),
                    retrieval_score=float(r.get("score") or 0.0),
                    attributes=_attrs(r.get("attrs")),
                )
                for r in rows
            ],
        )


class MariaDBTextSearchRetriever(Retriever):
    def __init__(
        self,
        db: Any,
        *,
        encoder=None,
        plugin_cfg: dict[str, Any] | None = None,
    ) -> None:
        self.db = _db(db)
        self.encoder = encoder
        self.plugin_cfg = plugin_cfg or {}

    def supports_prefilter(self, expr: A.Expr | str | None) -> bool:
        return supports_prefilter("text_search", expr)

    async def retrieve(self, req: RetrieveRequest) -> RetrieveBag:
        step = req.step
        name = getattr(step, "name", None) or "text_search"
        limit = int(getattr(step, "limit", 100) or 100)
        where = getattr(step, "where", None)
        if where is not None:
            assert_pushdown_or_raise("text_search", where)
        bindings = _bindings(req)
        renderer = QueryRenderer(bindings)
        items = bindings.entity(req.entity_type)
        q = _resolve_param(getattr(step, "input_text_query", ""), req.params or {})
        mode = step.mode
        mtype = getattr(mode, "type", None) or (
            mode.get("type") if isinstance(mode, dict) else None
        )

        if mtype == "vector":
            ref = getattr(mode, "text_embedding_ref", None) or (
                mode.get("text_embedding_ref") if isinstance(mode, dict) else None
            )
            ref = ref or "content_embedding"
            emb = bindings.embedding_store_for(str(ref), req.entity_type)
            qvec = vec_literal(encode_query(str(q), encoder=self.encoder))
            emb_structural, emb_binds = renderer.embedding_structural(
                emb,
                embedding_name=str(ref) if emb.name_column else None,
                entity_type=req.entity_type if emb.entity_type_column else None,
            )
            sql, args = renderer.render(
                "embedding_vector_search",
                structural={**renderer.entity_structural(items), **emb_structural},
                binds={"query_vector": qvec, "limit": limit, **emb_binds},
                store=emb,
            )
        else:
            structural = {**renderer.entity_structural(items)}
            sql, args = renderer.render(
                "lexical_fulltext",
                structural=structural,
                binds={"query_text": str(q), "limit": limit},
                entity=items,
            )
            if where:
                sql = sql.replace("ORDER BY", f"AND ({where})\nORDER BY", 1)

        rows = await fetch_all(self.db, sql, args)
        return RetrieveBag(
            name=str(name),
            candidates=[
                Candidate(
                    id=str(r["entity_id"]),
                    retrieval_score=float(r.get("score") or 0.0),
                    attributes=_attrs(r.get("attrs")),
                )
                for r in rows
            ],
        )


