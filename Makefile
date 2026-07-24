.PHONY: bootstrap dev-up dev-down dev-logs migrate seed test lint typecheck clean reset-local-data \
	openapi openapi-check terraform-validate help

ROOT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
UV ?= uv
PNPM ?= pnpm
COMPOSE ?= docker compose
export COMPOSE_PROJECT_NAME ?= societe

help:
	@echo "Société Make targets:"
	@echo "  bootstrap         Install Python/JS deps and create local .env"
	@echo "  dev-up            Start local Compose stack"
	@echo "  dev-down          Stop containers (keeps volumes)"
	@echo "  dev-logs          Tail API logs"
	@echo "  migrate           Run Alembic migrations"
	@echo "  seed              Seed synthetic LA venues and users"
	@echo "  test              Run Python tests"
	@echo "  lint              Run Ruff + mobile lint"
	@echo "  typecheck         Run mypy + mobile tsc"
	@echo "  openapi           Export OpenAPI from FastAPI"
	@echo "  openapi-check     Fail if OpenAPI drifted"
	@echo "  terraform-validate Validate Terraform (no apply)"
	@echo "  clean             Remove caches/build artifacts (not Docker volumes)"
	@echo "  reset-local-data  DESTRUCTIVE: delete local DB/MinIO volumes"

bootstrap:
	@command -v $(UV) >/dev/null || (echo "uv is required"; exit 1)
	@command -v $(PNPM) >/dev/null || (echo "pnpm is required"; exit 1)
	@if [ ! -f "$(ROOT_DIR)/.env" ]; then \
		cp "$(ROOT_DIR)/.env.example" "$(ROOT_DIR)/.env"; \
		SECRET=$$(openssl rand -hex 32); \
		CURSOR=$$(openssl rand -hex 32); \
		sed -i.bak "s/replace-me-with-openssl-rand-hex-32/$$SECRET/" "$(ROOT_DIR)/.env"; \
		sed -i.bak "s/replace-me-cursor-hmac/$$CURSOR/" "$(ROOT_DIR)/.env"; \
		rm -f "$(ROOT_DIR)/.env.bak"; \
		echo "Created .env with generated JWT_SECRET and CURSOR_HMAC_SECRET"; \
	fi
	cd "$(ROOT_DIR)" && $(UV) sync --all-packages
	cd "$(ROOT_DIR)" && $(PNPM) install
	@echo "Bootstrap complete. Start Docker Desktop, then: make dev-up"

dev-up:
	@docker info >/dev/null 2>&1 || (echo "Docker daemon is not running. Start Docker Desktop."; exit 1)
	cd "$(ROOT_DIR)" && $(COMPOSE) up -d --build
	@echo "Stack starting. API: http://localhost:8000  Mailpit: http://localhost:8025"

dev-down:
	cd "$(ROOT_DIR)" && $(COMPOSE) down

dev-logs:
	cd "$(ROOT_DIR)" && $(COMPOSE) logs -f api

migrate:
	cd "$(ROOT_DIR)/services/api" && $(UV) run --project "$(ROOT_DIR)" alembic upgrade head

seed:
	cd "$(ROOT_DIR)" && set -a && . ./.env && set +a && $(UV) run python scripts/seed_local.py

test:
	cd "$(ROOT_DIR)" && $(UV) run pytest

lint:
	cd "$(ROOT_DIR)" && $(UV) run ruff check services/api
	cd "$(ROOT_DIR)" && $(UV) run ruff format --check services/api
	@if [ -d "$(ROOT_DIR)/apps/mobile" ]; then cd "$(ROOT_DIR)" && $(PNPM) lint; fi

typecheck:
	cd "$(ROOT_DIR)" && $(UV) run mypy
	@if [ -d "$(ROOT_DIR)/apps/mobile" ]; then cd "$(ROOT_DIR)" && $(PNPM) typecheck; fi

openapi:
	cd "$(ROOT_DIR)" && $(UV) run python scripts/export_openapi.py

openapi-check:
	cd "$(ROOT_DIR)" && $(UV) run python scripts/export_openapi.py --check

terraform-validate:
	cd "$(ROOT_DIR)/infra/terraform/environments/dev" && terraform init -backend=false -input=false
	cd "$(ROOT_DIR)/infra/terraform/environments/dev" && terraform validate

clean:
	find "$(ROOT_DIR)" -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf "$(ROOT_DIR)/.pytest_cache" "$(ROOT_DIR)/.mypy_cache" "$(ROOT_DIR)/.ruff_cache"
	rm -rf "$(ROOT_DIR)/apps/mobile/.expo" "$(ROOT_DIR)/apps/mobile/dist" 2>/dev/null || true
	@echo "Cleaned caches. Docker volumes were NOT deleted."

reset-local-data:
	@echo "WARNING: This deletes local PostgreSQL and MinIO Docker volumes for project '$(COMPOSE_PROJECT_NAME)'."
	@echo "Press Ctrl-C within 5 seconds to abort..."
	@sleep 5
	cd "$(ROOT_DIR)" && $(COMPOSE) down
	cd "$(ROOT_DIR)" && $(COMPOSE) down -v
	@echo "Local volumes removed."
