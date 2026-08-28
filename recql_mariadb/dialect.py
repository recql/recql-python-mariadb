"""MariaDB SQL dialect — aiomysql ``%s`` binds + JSON entity fragments."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

from recql.plugins.dialect import (
    NamedBindDialect,
    _common_select_tail,
    _iter_order_columns,
    register_sql_dialect,
)

if TYPE_CHECKING:
    from recql.catalog.bindings import EntityTableBinding


class MariaDBDialect(NamedBindDialect):
    def select_entity_columns(
        self, binding: "EntityTableBinding", *, alias: str = "e"
    ) -> str:
        if binding.attrs_json_column:
            attrs_sql = f"{alias}.{binding.attrs_json_column} AS attrs"
        elif binding.attribute_columns:
            pairs = ", ".join(
                f"'{c}', {alias}.{c}" for c in binding.attribute_columns
            )
            extra = [f"{alias}.{c}" for c in binding.attribute_columns]
            attrs_sql = f"JSON_OBJECT({pairs}) AS attrs"
            parts = _common_select_tail(binding, alias=alias, attrs_sql=attrs_sql)
            parts = [parts[0], *extra, *parts[1:]]
            return ", ".join(parts)
        else:
            # No attrs column / feature list — empty JSON object (caller should set schema).
            attrs_sql = "CAST('{}' AS JSON) AS attrs"
        return ", ".join(_common_select_tail(binding, alias=alias, attrs_sql=attrs_sql))

    def order_by_sql(
        self,
        binding: "EntityTableBinding",
        columns: list[Any],
        *,
        alias: str = "e",
    ) -> str:
        parts: list[str] = []
        for cname, asc, _nulls_first in _iter_order_columns(columns):
            direction = "ASC" if asc else "DESC"
            # MariaDB lacks NULLS FIRST/LAST; ASC/DESC only.
            if cname in (
                binding.popular_rank_column,
                "_derived_popular_rank",
                "derived_popular_rank",
            ):
                col = binding.popular_rank_column or cname
                parts.append(f"{alias}.{col} {direction}")
            elif cname in (binding.created_at_column, "created_at"):
                col = binding.created_at_column or cname
                parts.append(f"{alias}.{col} {direction}")
            elif binding.attrs_json_column:
                parts.append(
                    f"JSON_VALUE({alias}.{binding.attrs_json_column}, '$.{cname}') "
                    f"{direction}"
                )
            else:
                parts.append(f"{alias}.{cname} {direction}")
        return ", ".join(parts)

    def render_entity_by_ids(
        self, renderer: Any, binding: "EntityTableBinding", ids: list[str]
    ) -> tuple[str, list[Any]]:
        placeholders = ", ".join(["%s"] * len(ids))
        quoted = ", ".join("'" + iid.replace("'", "''") + "'" for iid in ids)
        tpl = renderer.resolve("entity_by_ids", entity=binding)
        sql = tpl.format(
            **renderer.entity_structural(binding),
            id_in_list=placeholders,
            id_field_list=quoted,
        )
        return sql, list(ids)


DIALECT = register_sql_dialect(
    MariaDBDialect(
        name="mariadb",
        placeholder=lambda i: "%s",
        queries_path=Path(__file__).resolve().parent / "queries.yaml",
        aliases=("maria", "mysql"),
    ),
    "maria",
    "mysql",
)


def register():
    """Entry-point hook for ``recql.dialects`` (dialect already registered on import)."""
    return DIALECT
