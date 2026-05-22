# AI Werewolf — common dev/ops shortcuts
# Run `make help` to see the full list.

.PHONY: help install demo dev test smoke human-smoke db-up db-down db-shell db-init db-migrate \
        compose-up compose-down compose-logs lint clean

PYTHON ?= python
PORT   ?= 8000
SEED   ?= 7

help:
	@echo "AI Werewolf Makefile"
	@echo ""
	@echo "  make install       — pip install -r requirements.txt"
	@echo "  make demo          — run one offline AI vs AI game (seed=$(SEED))"
	@echo "  make dev           — start FastAPI (port $(PORT)) with reload"
	@echo "  make test          — run pytest unit suite"
	@echo "  make smoke         — run scripts/e2e_smoke.py"
	@echo "  make human-smoke   — run scripts/human_smoke.py (server must be up)"
	@echo "  make db-up         — start the Postgres container (port 5433)"
	@echo "  make db-down       — stop the Postgres container"
	@echo "  make db-shell      — psql shell into the container"
	@echo "  make db-init       — create / refresh schema in the configured DB"
	@echo "  make db-migrate    — copy historical games from data/werewolf.db into PG (idempotent)"
	@echo "  make compose-up    — bring up the full stack (postgres + backend)"
	@echo "  make compose-down  — tear the full stack down"
	@echo "  make compose-logs  — tail backend logs"
	@echo "  make clean         — remove caches and the local sqlite DB"

install:
	$(PYTHON) -m pip install -r requirements.txt

demo:
	$(PYTHON) -m backend.run_demo --seed $(SEED)

dev:
	$(PYTHON) -m uvicorn backend.app:app --host 0.0.0.0 --port $(PORT) --reload

test:
	$(PYTHON) -m pytest tests/test_engine.py tests/test_llm_config.py tests/test_api.py -x --tb=short

smoke:
	$(PYTHON) scripts/e2e_smoke.py

human-smoke:
	$(PYTHON) scripts/human_smoke.py

db-up:
	docker start werewolf-pg 2>/dev/null || \
	docker run -d --name werewolf-pg --restart unless-stopped \
	  -e POSTGRES_USER=werewolf -e POSTGRES_PASSWORD=wolf_secret_2026 -e POSTGRES_DB=werewolf \
	  -p 5433:5432 -v werewolf-pg-data:/var/lib/postgresql/data \
	  postgres:16-alpine

db-down:
	docker stop werewolf-pg || true

db-shell:
	docker exec -it werewolf-pg psql -U werewolf -d werewolf

db-init:
	$(PYTHON) -c "from backend.db.database import init_db; init_db(); print('schema created')"

db-migrate:
	$(PYTHON) scripts/migrate_sqlite_to_pg.py

compose-up:
	docker compose up -d --build

compose-down:
	docker compose down

compose-logs:
	docker compose logs -f backend

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -f data/werewolf.db
