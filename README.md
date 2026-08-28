# recql-mariadb

Standalone RecQL backend for MariaDB 11.7+.

## Conformance tests

```bash
make test-conformance-docker   # recommended
# or: make up && make test-conformance
```

Host port defaults to **3307** (`MARIADB_PORT`) so it does not collide with
playground MariaDB on 3306. Inside Compose the DSN still uses `mariadb:3306`.
