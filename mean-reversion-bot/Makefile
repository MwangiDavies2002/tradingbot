# ─────────────────────────────────────────────────────────────────────────────
# Mean Reversion Bot — Makefile
# Run `make help` to see all available commands.
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: help up down logs build test lint backtest run-bot run-api db-shell redis-cli migrate clean

# ── Default ───────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  Mean Reversion Bot — Developer Commands"
	@echo "  ─────────────────────────────────────────────"
	@echo "  DOCKER"
	@echo "    make up           Start redis + api (database runs in Laragon)"
	@echo "    make up-all       Start everything inc bot + frontend"
	@echo "    make down         Stop all containers"
	@echo "    make logs         Tail all container logs"
	@echo "    make build        Rebuild Docker images"
	@echo ""
	@echo "  DEVELOPMENT"
	@echo "    make run-api      Run FastAPI locally (no Docker)"
	@echo "    make run-bot      Run bot locally (no Docker)"
	@echo "    make run-frontend Start React dev server"
	@echo ""
	@echo "  TESTING"
	@echo "    make test         Run all unit + integration tests"
	@echo "    make test-unit    Run unit tests only"
	@echo "    make lint         Run ruff + black check"
	@echo "    make backtest     Run backtest smoke test"
	@echo ""
	@echo "  DATABASE"
	@echo "    make migrate      Run Alembic migrations"
	@echo "    make db-shell     Open a MySQL shell"
	@echo "    make redis-cli    Open redis-cli"
	@echo ""
	@echo "  UTILS"
	@echo "    make clean        Remove __pycache__ and .pyc files"
	@echo "    make secret       Generate a new SECRET_KEY"
	@echo ""

# ── Docker ────────────────────────────────────────────────────────────────────
up:
	docker compose up -d redis api

up-all:
	docker compose --profile bot --profile frontend up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

build:
	docker compose build --no-cache

# ── Local Development ─────────────────────────────────────────────────────────
run-api:
	cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --log-level info

run-bot:
	cd backend && python -m app.bot

run-frontend:
	cd frontend && npm run dev

# ── Testing ───────────────────────────────────────────────────────────────────
test:
	cd backend && python -m pytest tests/ -v --tb=short

test-unit:
	cd backend && python -m pytest tests/unit/ -v --tb=short

test-integration:
	cd backend && python -m pytest tests/integration/ -v --tb=short

lint:
	cd backend && ruff check app/ && black --check app/

format:
	cd backend && black app/ && ruff check --fix app/

backtest:
	cd backend && python -c "\
import sys; sys.path.insert(0, '.'); \
import random; random.seed(42); \
from app.core.lsl.lsl_detector import Candle; \
from app.core.engine.signal_engine import SignalEngine, EngineConfig; \
from app.backtesting.backtest_engine import BacktestEngine; \
candles = [Candle(1700000000+i*300, 1948+random.gauss(0,0.8), \
           1950+abs(random.gauss(0,0.4)), 1946-abs(random.gauss(0,0.4)), \
           1948+random.gauss(0,0.8), random.uniform(800,2000)) for i in range(200)]; \
engine = SignalEngine(EngineConfig(min_confluence=6)); \
engine.initialise(1000.0); \
bt = BacktestEngine(signal_engine=engine, initial_balance=1000.0); \
report = bt.run(candles, symbol='XAUUSD', timeframe='M5'); \
print(report.summary())"

# ── Database ──────────────────────────────────────────────────────────────────
migrate:
	cd backend && alembic upgrade head

migrate-down:
	cd backend && alembic downgrade -1

db-shell:
	mysql -h 127.0.0.1 -P 3306 -u root meanrevbot

redis-cli:
	docker exec -it mrbot_redis redis-cli

# ── Utils ─────────────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true

secret:
	@python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"

install:
	cd backend  && pip install -r requirements.txt
	cd frontend && npm install

.DEFAULT_GOAL := help
