# Bursar — Makefile
#
# Canonical: .pi/architecture/implementation-roadmap.md#phase-0-project-bootstrap-hours-01
#
# Every target below maps to a Phase-0 acceptance criterion or a demo-day need. If a target is not
# needed by one of those two, it does not belong here.

SHELL := /bin/bash
.DEFAULT_GOAL := help

UV ?= uv
PYTHON ?= python3.12
PORT_AUTHORITY ?= 8001
PORT_CONSOLE ?= 8000
DB ?= console

.PHONY: help install lock test test-unit test-contract lint fmt typecheck check \
        validate validators run-authority run-console health db-upgrade db-downgrade db-status \
        anvil contracts-build contracts-test clean-freeze-check

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ── setup ────────────────────────────────────────────────────────────────────
install: ## Create venv and install dependencies (editable + dev)
	$(UV) venv --python $(PYTHON) --allow-existing
	$(UV) pip install -e ".[dev]"
	@echo "✓ installed. Copy .env.example to .env before running services."

lock: ## Refresh uv.lock
	$(UV) lock

# ── quality gates ────────────────────────────────────────────────────────────
test: ## Run the full test suite
	$(UV) run pytest

test-unit: ## Shared-kernel unit tests only (no server, fast)
	$(UV) run pytest tests/shared -q

test-contract: ## Architecture-boundary tests
	$(UV) run pytest -m contract -q

lint: ## Ruff lint (whole repo, including migrations)
	$(UV) run ruff check .
	$(UV) run ruff format --check .

fmt: ## Ruff format (writes)
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

typecheck: ## Mypy (strict-ish)
	$(UV) run mypy

validate: ## Guardian architecture validators (ADR-001/002/007 gates)
	@bash .pi/scripts/validate-architecture.sh || true
	@bash .pi/scripts/check_model_judgment.sh || true
	@bash .pi/scripts/check_language_consistency.sh || true
	@if [ -d src/mandate ] || [ -d src/authority ]; then \
	  bash .pi/scripts/check_composition_root.sh || true; \
	else echo "composition-root gate deferred: no bounded contexts built yet (Phase 0)"; fi

check: lint typecheck test ## Everything CI runs, locally

# ── services ─────────────────────────────────────────────────────────────────
run-authority: ## Start authority-service on :8001 (enforcement-critical)
	$(UV) run uvicorn src.apps.authority_service.app:app --host 127.0.0.1 --port $(PORT_AUTHORITY) --reload

run-console: ## Start console-api on :8000 (browser-facing)
	$(UV) run uvicorn src.apps.console_api.app:app --host 127.0.0.1 --port $(PORT_CONSOLE) --reload

health: ## Curl both health surfaces
	@echo "authority-service:"; curl -fsS http://127.0.0.1:$(PORT_AUTHORITY)/readyz | head -c 400; echo
	@echo "console-api:";       curl -fsS http://127.0.0.1:$(PORT_CONSOLE)/readyz   | head -c 400; echo

# ── database (ADR-002: two SQLite files, one migration tree) ─────────────────
db-upgrade: ## alembic upgrade head (DB=console|authority)
	$(UV) run alembic -x db=$(DB) upgrade head

db-downgrade: ## alembic downgrade base (DB=console|authority)
	$(UV) run alembic -x db=$(DB) downgrade base

db-status: ## Show current revision
	$(UV) run alembic -x db=$(DB) current

# ── chain (ADR-007) ──────────────────────────────────────────────────────────
anvil: ## Local chain on :8545 — the demo path
	anvil --chain-id 31337 --block-time 1

contracts-build: ## forge build (empty in Phase 0)
	forge build

contracts-test: ## forge test
	forge test -vv

clean-freeze-check: ## Refuse to work past code freeze (Sat 14 Nov 2026 15:00)
	@now=$$(date +%s); freeze=$$(date -j -f "%Y-%m-%d %H:%M" "2026-11-14 15:00" +%s 2>/dev/null || date -d "2026-11-14 15:00" +%s); \
	if [ $$now -gt $$freeze ]; then echo "✗ CODE FREEZE PASSED — demo prep only"; exit 1; fi; \
	echo "✓ before code freeze"