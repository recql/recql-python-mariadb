"""MariaDB-specific helpers (DSN / VECTOR literals)."""

from __future__ import annotations

from recql_mariadb.db import parse_mariadb_dsn, quote_ident, vec_literal


def test_parse_mariadb_dsn():
    kw = parse_mariadb_dsn("mariadb://recql:secret@127.0.0.1:3307/recql")
    assert kw["host"] == "127.0.0.1"
    assert kw["port"] == 3307
    assert kw["user"] == "recql"
    assert kw["password"] == "secret"
    assert kw["db"] == "recql"


def test_parse_mysql_alias():
    kw = parse_mariadb_dsn("mysql://u:p@db:3306/app")
    assert kw["user"] == "u"
    assert kw["db"] == "app"


def test_vec_literal():
    assert vec_literal([0.1, 0.2]) == "[0.1,0.2]"
    assert vec_literal("[1,2]") == "[1,2]"


def test_quote_ident_escapes_backticks():
    assert quote_ident("blob") == "`blob`"
    assert quote_ident("a`b") == "`a``b`"
