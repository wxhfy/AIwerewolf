# ============================================================================
# AI Werewolf — Makefile
# ============================================================================
# Quick reference:
#   make deploy        — one-command production deploy (Docker full stack)
#   make dev           — local development server
# ============================================================================

PYTHON  ?= python
ENV_FILE ?= .env
APP_HOST ?= $(shell sed -n 's/^APP_HOST=//p' $(ENV_FILE) 2>/dev/null | tail -1)
APP_HOST := $(or $(APP_HOST),0.0.0.0)
BACKEND_PORT ?= $(shell sed -n 's/^BACKEND_PORT=//p' $(ENV_FILE) 2>/dev/null | tail -1)
BACKEND_PORT := $(or $(BACKEND_PORT),8000)
FRONTEND_PORT ?= $(shell sed -n 's/^FRONTEND_PORT=//p' $(ENV_FILE) 2>/dev/null | tail -1)
FRONTEND_PORT := $(or $(FRONTEND_PORT),3001)
POSTGRES_PORT ?= $(shell sed -n 's/^POSTGRES_PORT=//p' $(ENV_FILE) 2>/dev/null | tail -1)
POSTGRES_PORT := $(or $(POSTGRES_PORT),5433)
POSTGRES_USER ?= $(shell sed -n 's/^POSTGRES_USER=//p' $(ENV_FILE) 2>/dev/null | tail -1)
POSTGRES_USER := $(or $(POSTGRES_USER),werewolf)
POSTGRES_PASSWORD ?= $(shell sed -n 's/^POSTGRES_PASSWORD=//p' $(ENV_FILE) 2>/dev/null | tail -1)
POSTGRES_PASSWORD := $(or $(POSTGRES_PASSWORD),wolf_secret_2026)
POSTGRES_DB ?= $(shell sed -n 's/^POSTGRES_DB=//p' $(ENV_FILE) 2>/dev/null | tail -1)
POSTGRES_DB := $(or $(POSTGRES_DB),werewolf)
NGINX_PORT ?= $(shell sed -n 's/^NGINX_PORT=//p' $(ENV_FILE) 2>/dev/null | tail -1)
NGINX_PORT := $(or $(NGINX_PORT),80)
PORT    ?= $(BACKEND_PORT)
SEED    ?= 7
COMPOSE := docker compose --env-file $(ENV_FILE)

# ------------------------------------------------------------------
# 🚀  One-command Deploy
# ------------------------------------------------------------------

.PHONY: deploy deploy-dev deploy-down deploy-logs deploy-status

deploy: .env
	@echo "🐺  AI Werewolf — Production Deploy"
	@echo "========================================"
	$(COMPOSE) up -d --build --wait
	@echo ""
	@echo "✅  Deploy complete!"
	@echo "    Frontend : http://localhost:$(NGINX_PORT)"
	@echo "    API      : http://localhost:$(NGINX_PORT)/api"
	@echo "    Swagger  : http://localhost:$(NGINX_PORT)/api/docs"

deploy-dev: .env
	@echo "🐺  AI Werewolf — Dev Deploy (hot-reload)"
	@echo "========================================"
	$(COMPOSE) --profile dev up -d --build
	@echo ""
	@echo "✅  Dev deploy complete!"
	@echo "    Backend  : http://localhost:$(BACKEND_PORT)"
	@echo "    Frontend : http://localhost:$(FRONTEND_PORT)"

deploy-down:
	$(COMPOSE) down -v

deploy-logs:
	$(COMPOSE) logs -f

deploy-status:
	@$(COMPOSE) ps

# ------------------------------------------------------------------
# 🛠  Local Development
# ------------------------------------------------------------------

.PHONY: install dev demo test lint format

install:
	$(PYTHON) -m pip install -r requirements.txt
	cd frontend && npm install --legacy-peer-deps

dev:
	$(PYTHON) -m uvicorn backend.app:app --host 0.0.0.0 --port $(PORT) --reload

frontend-dev:
	cd frontend && PORT=$(FRONTEND_PORT) npm run dev

demo:
	$(PYTHON) -m backend.run_demo --seed $(SEED)

test:
	$(PYTHON) -m pytest tests/ -x --tb=short -q

test-strict:
	$(PYTHON) scripts/run_backend_full_strict.py

test-visibility:
	$(PYTHON) scripts/verify_visibility_strict.py

lint:
	$(PYTHON) -m ruff check backend/ scripts/ tests/ configs/
	$(PYTHON) -m ruff format --check backend/ scripts/ tests/ configs/

format:
	$(PYTHON) -m ruff check --fix backend/ scripts/ tests/ configs/
	$(PYTHON) -m ruff format backend/ scripts/ tests/ configs/

# ------------------------------------------------------------------
# 🗄  Database
# ------------------------------------------------------------------

.PHONY: db-up db-down db-shell db-init db-migrate

db-up:
	docker start werewolf-pg 2>/dev/null || \
	docker run -d --name werewolf-pg --restart unless-stopped \
	  -e POSTGRES_USER=$(POSTGRES_USER) -e POSTGRES_PASSWORD=$(POSTGRES_PASSWORD) \
	  -e POSTGRES_DB=$(POSTGRES_DB) \
	  -p $(POSTGRES_PORT):5432 -v werewolf-pg-data:/var/lib/postgresql/data \
	  postgres:16-alpine

db-down:
	docker stop werewolf-pg || true

db-shell:
	docker exec -it werewolf-pg psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

db-init:
	$(PYTHON) -c "from backend.db.database import init_db; init_db(); print('Schema created')"

db-migrate:
	$(PYTHON) scripts/migrate_sqlite_to_pg.py

# ------------------------------------------------------------------
# 🧹  Utilities
# ------------------------------------------------------------------

.PHONY: preflight clean nuke help

preflight:
	$(PYTHON) -m backend.ops.preflight

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -f data/werewolf.db

nuke: deploy-down clean
	docker volume rm werewolf-pg-data 2>/dev/null || true
	docker rmi aiwerewolf-backend aiwerewolf-frontend 2>/dev/null || true
	@echo "🧹  All containers, volumes, and images removed"

help:
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "🐺  AI Werewolf — Makefile"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "🚀  Deploy (Docker)"
	@echo "  make deploy         — full stack: nginx + backend + frontend + postgres"
	@echo "  make deploy-dev      — dev mode with hot-reload"
	@echo "  make deploy-down     — stop everything"
	@echo "  make deploy-logs     — tail all service logs"
	@echo "  make deploy-status   — show running containers"
	@echo ""
	@echo "🛠  Development"
	@echo "  make install         — pip install + npm install"
	@echo "  make dev             — start FastAPI (reload, port $(PORT))"
	@echo "  make frontend-dev    — start Next.js (port $(FRONTEND_PORT))"
	@echo "  make demo            — one offline AI vs AI game (seed=$(SEED))"
	@echo ""
	@echo "🧪  Testing"
	@echo "  make test            — unit tests"
	@echo "  make test-strict     — full strict-mode validation"
	@echo "  make test-visibility — information isolation check (92 items)"
	@echo "  make lint            — ruff check + format check"
	@echo "  make format          — ruff auto-fix + format"
	@echo ""
	@echo "🗄  Database"
	@echo "  make db-up           — start PostgreSQL (port 5433)"
	@echo "  make db-down         — stop PostgreSQL"
	@echo "  make db-shell        — psql shell"
	@echo "  make db-init         — create / refresh schema"
	@echo ""
	@echo "🧹  Utilities"
	@echo "  make preflight       — 7-item startup check"
	@echo "  make clean           — remove caches + sqlite DB"
	@echo "  make nuke            — remove ALL containers + volumes + images"
	@echo ""

# ------------------------------------------------------------------
# Ensure .env exists
# ------------------------------------------------------------------
.env:
	@echo "⚠️  .env not found — copying .env.example"
	@cp .env.example .env
	@echo "🔧  Edit .env with your API keys, then re-run make"
	@exit 1
