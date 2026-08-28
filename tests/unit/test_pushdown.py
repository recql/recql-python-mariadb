"""MariaDB pushdown capability matrix unit tests."""

from __future__ import annotations

import pytest

from recql.errors import ExecuteError
from recql_mariadb.pushdown import (
    MARIADB_PUSHDOWN,
    PrefilterShape,
    assert_pushdown_or_raise,
    classify_prefilter,
    supports_prefilter,
)


def test_matrix_covers_all_retrieve_types():
    expected = {
        "filter",
        "candidate_attributes",
        "column_order",
        "text_search",
        "similarity",
        "candidate_ids",
    }
    assert set(MARIADB_PUSHDOWN) == expected


def test_classify_shapes():
    assert classify_prefilter(None) is PrefilterShape.NONE
    assert classify_prefilter("category = 'electronics'") is PrefilterShape.EQUALITY
    assert classify_prefilter("price BETWEEN 10 AND 20") is PrefilterShape.RANGE
    assert classify_prefilter("id IN ('a','b')") is PrefilterShape.IN_LIST
    assert classify_prefilter("name LIKE '%x%'") is PrefilterShape.LIKE
    assert classify_prefilter("haversine_distance(a,b,c,d) < 5") is PrefilterShape.FUNCTION


def test_similarity_fails_closed_on_any_where():
    assert supports_prefilter("similarity", None)
    assert not supports_prefilter("similarity", "category = 'x'")
    with pytest.raises(ExecuteError, match="fail closed"):
        assert_pushdown_or_raise("similarity", "category = 'x'")


def test_column_order_allows_equality_rejects_range():
    assert supports_prefilter("column_order", "category = 'electronics'")
    assert not supports_prefilter("column_order", "price > 100")
    with pytest.raises(ExecuteError, match="fail closed"):
        assert_pushdown_or_raise("column_order", "price > 100")


def test_filter_allows_arbitrary():
    assert supports_prefilter("filter", "price > 100 AND array_has(tags, 'a')")
