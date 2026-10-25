IMAGE := oracle
CONTAINER := oracle
VOLUME := oracle-data
PORT := 8080
SMOKE_IMAGE := oracle-smoke
SMOKE_MODELS := oracle-smoke-models

.DEFAULT_GOAL := help

.PHONY: help setup up down logs cli-run cli-test server-run server-test backend-test backend-lint backend-embedding-check backend-audit backend-licenses frontend-run frontend-test frontend-e2e frontend-lint frontend-audit frontend-licenses docker-smoke-build docker-smoke-run docker-smoke test lint audit licenses

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-16s %s\n", $$1, $$2}'

setup: ## Install backend and frontend deps, plus Playwright's browser binaries
	cd backend && uv sync
	cd frontend && pnpm install
	cd frontend && pnpm exec playwright install

up: ## Build and run the whole app in docker at http://localhost:8080
	docker build -t $(IMAGE) .
	@docker stop $(CONTAINER) >/dev/null 2>&1 || true
	@docker rm -f $(CONTAINER) >/dev/null 2>&1 || true
	docker run -d --init --name $(CONTAINER) -p $(PORT):80 -v $(VOLUME):/data $(IMAGE)
	@echo "Running at http://localhost:$(PORT)"

down: ## Stop and remove the docker container (the data volume is kept)
	docker stop $(CONTAINER)
	docker rm $(CONTAINER)

logs: ## Tail the docker container logs
	docker logs -f $(CONTAINER)

docker-smoke-build: ## Build the image the smoke test runs (tagged $(SMOKE_IMAGE))
	docker build -t $(SMOKE_IMAGE) .

docker-smoke-run: ## Smoke-test the built image on a throwaway data volume (model cache: SMOKE_MODELS)
	python3 scripts/docker_smoke.py --image $(SMOKE_IMAGE) --models $(SMOKE_MODELS)

docker-smoke: docker-smoke-build docker-smoke-run ## Build the image and smoke-test it (never touches oracle-data)

cli-run: ## Run the CLI; pass arguments via ARGS="--help"
	cd backend && uv run oracle-cli $(ARGS)

cli-test: ## Run the CLI and common tests
	cd backend && uv run pytest --ignore=tests/test_server_app.py

server-run: ## Run the API server on 127.0.0.1:8000 (dev, no docker)
	cd backend && uv run oracle-server

server-test: ## Run the API server and common tests
	cd backend && uv run pytest --ignore=tests/test_cli_main.py

backend-test: ## Run the full backend test suite (CLI, server, common)
	cd backend && uv run pytest

backend-lint: ## Lint, format-check and typecheck the backend and scripts/ (ruff + ty)
	cd backend && uv run ruff check . ../scripts && uv run ruff format --check . ../scripts && uv run ty check . ../scripts

backend-embedding-check: ## Check the real embedding model still matches its golden vectors (downloads ~130MB on first run)
	cd backend && uv run pytest -m embedding_model tests/test_embedding_stability.py

backend-audit: ## Check backend dependencies for known vulnerabilities (uv audit)
	cd backend && uv audit

backend-licenses: ## Check backend dependency licenses against the allowlist (needs make setup)
	python3 scripts/check_licenses.py backend

frontend-run: ## Run the Vite dev server on 127.0.0.1:5173 (needs server-run)
	cd frontend && pnpm dev --host

frontend-test: ## Run the frontend unit tests (Vitest)
	cd frontend && pnpm test

frontend-e2e: ## Run the frontend end-to-end tests (Playwright)
	cd frontend && pnpm test:e2e

frontend-lint: ## Typecheck the frontend (vue-tsc)
	cd frontend && pnpm typecheck

frontend-audit: ## Check frontend dependencies for known vulnerabilities (pnpm audit)
	cd frontend && pnpm audit

frontend-licenses: ## Check frontend dependency licenses against the allowlist (needs make setup)
	python3 scripts/check_licenses.py frontend

test: backend-test frontend-test ## Run all test suites

lint: backend-lint frontend-lint ## Lint and typecheck the whole project

audit: backend-audit frontend-audit ## Check all dependencies for known vulnerabilities

licenses: backend-licenses frontend-licenses ## Check all dependency licenses against the allowlist
