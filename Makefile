.DEFAULT_GOAL := help

COMPOSE ?= docker compose
PYTHON ?= $(shell command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)
PYTEST ?= $(PYTHON) -m pytest
# Host port 3307 by default (compose maps → container 3306). Avoids clash with
# playground MariaDB on 3306.
MARIADB_PORT ?= 3307
DSN ?= mariadb://recql:recql@127.0.0.1:$(MARIADB_PORT)/recql
RECQL_CORE_PATH ?= ../recql-python-core
RECQL_PLAYGROUND_PATH ?= ../recql-playground

export MARIADB_PORT
export RECQL_CORE_PATH
export RECQL_PLAYGROUND_PATH

.PHONY: help up down reset logs test test-unit test-conformance test-conformance-docker build-conformance

help: ## Show targets
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_-]+:.*## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf '\nDocker (recommended): make test-conformance-docker\n'
	@printf 'Default host port is $(MARIADB_PORT) (set MARIADB_PORT=… to override).\n'
	@printf 'Host DSN default: $(DSN)\n'

up: ## Start MariaDB 11.7+ and wait for healthy
	$(COMPOSE) up -d mariadb
	@echo "waiting for healthy… (DSN=$(DSN))"
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do \
	  st=$$($(COMPOSE) ps mariadb --format '{{.Health}}' 2>/dev/null || true); \
	  if [ "$$st" = "healthy" ]; then echo "mariadb healthy"; exit 0; fi; \
	  if $(COMPOSE) ps -a mariadb --format '{{.Status}}' 2>/dev/null | grep -qi exited; then \
	    echo "mariadb exited — see: make logs"; exit 1; \
	  fi; \
	  sleep 2; \
	done; \
	echo "timed out waiting for healthy"; exit 1

down: ## Stop containers (keep volumes)
	$(COMPOSE) down

reset: ## Wipe MariaDB volume and stop
	$(COMPOSE) down -v

logs: ## Tail MariaDB logs
	$(COMPOSE) logs -f mariadb

build-conformance: ## Build the conformance runner image
	$(COMPOSE) --profile conformance build conformance

test-unit: ## Backend-specific unit tests (no DB)
	@command -v $(PYTHON) >/dev/null || { echo "No $(PYTHON) on PATH"; exit 127; }
	$(PYTEST) tests/unit -q

test-conformance: ## Shared suite on the host (needs make up + local installs)
	@command -v $(PYTHON) >/dev/null || { echo "No $(PYTHON) on PATH — use: make test-conformance-docker"; exit 127; }
	RECQL_MARIADB_DSN=$(DSN) $(PYTEST) tests/ -q

test-conformance-docker: ## Start MariaDB + run suite inside Docker (recommended)
	@$(MAKE) up
	$(COMPOSE) --profile conformance run --rm --build conformance

test: test-conformance-docker ## Default: full docker conformance
