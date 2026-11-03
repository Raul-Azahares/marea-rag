SHELL        := /bin/bash
COMPOSE      := docker compose
TEST_COMPOSE := docker compose -f docker-compose.test.yml
BACKEND      := cd backend &&
FRONTEND     := cd frontend &&

.DEFAULT_GOAL := help
.PHONY: help up down clean logs ps install lint fmt test test-unit test-infra test-infra-down samples \
        frontend-install frontend-dev frontend-check eval eval-real eval-sweep

help: ## List the available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ------------------------------------------------------------------- full stack
up: ## Build and start the whole stack, waiting until it is healthy
	$(COMPOSE) up --build -d --wait

down: ## Stop the stack (data volumes are kept)
	$(COMPOSE) down

clean: ## Stop the stack and delete its data volumes
	$(COMPOSE) down -v

logs: ## Follow the logs of every service
	$(COMPOSE) logs -f --tail=100

ps: ## Show the status of every service
	$(COMPOSE) ps

# ---------------------------------------------------------------------- backend
install: ## Install the backend dependencies locally (uv)
	$(BACKEND) uv sync --frozen

lint: ## Lint, format-check and type-check the backend
	$(BACKEND) uv run ruff check . && uv run ruff format --check . && uv run mypy app evaluation

fmt: ## Auto-format the backend and apply safe lint fixes
	$(BACKEND) uv run ruff format . && uv run ruff check --fix .

samples: ## Regenerate the synthetic sample PDFs (deterministic output)
	uv run --project backend python samples/generate_samples.py

# --------------------------------------------------------------------- frontend
frontend-install: ## Install the frontend dependencies exactly as locked (npm ci)
	$(FRONTEND) npm ci --ignore-scripts

frontend-dev: ## Vite dev server on :5173, proxying /api to the API on :8000
	$(FRONTEND) npm run dev

frontend-check: ## Lint, type-check, test and build the frontend
	$(FRONTEND) npm run lint -- --max-warnings 0 && npm run typecheck && npm test && npm run build

# ------------------------------------------------------------------------ tests
test-infra: ## Start throwaway Postgres + Redis for the tests (ports 55432 / 56379)
	$(TEST_COMPOSE) up -d --wait

test-infra-down: ## Stop the test infrastructure
	$(TEST_COMPOSE) down -v

test-unit: ## Run the unit tests only (no infrastructure needed)
	$(BACKEND) uv run pytest -m "not integration and not e2e"

test: test-infra ## Run the whole backend test suite
	$(BACKEND) uv run pytest

# ------------------------------------------------------------------- evaluation
eval: test-infra ## Evaluate with the deterministic fake providers and enforce the quality gate
	$(BACKEND) uv run python -m evaluation run --gate

eval-real: test-infra ## Evaluate with the providers configured in .env (e.g. Gemini); report only
	$(BACKEND) set -a && . ../.env && set +a && uv run python -m evaluation run --label real

eval-sweep: test-infra ## Chunking sweep (retrieval only) with the fake embeddings
	$(BACKEND) uv run python -m evaluation sweep
