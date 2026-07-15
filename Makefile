IMAGE := oracle
CONTAINER := oracle
VOLUME := oracle-data
PORT := 8080

.DEFAULT_GOAL := help

.PHONY: help setup up down logs cli-run cli-test server-run server-test backend-test backend-lint frontend-run frontend-test frontend-e2e frontend-lint test lint

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-16s %s\n", $$1, $$2}'

setup: ## Install backend and frontend deps, plus Playwright's browser binaries
	cd backend && uv sync
	cd frontend && pnpm install
	cd frontend && pnpm exec playwright install

up: ## Build and run the whole app in docker at http://localhost:8080
	docker build -t $(IMAGE) .
	@docker rm -f $(CONTAINER) >/dev/null 2>&1 || true
	docker run -d --name $(CONTAINER) -p $(PORT):80 -v $(VOLUME):/data $(IMAGE)
	@echo "Running at http://localhost:$(PORT)"

down: ## Stop and remove the docker container (the data volume is kept)
	docker rm -f $(CONTAINER)

logs: ## Tail the docker container logs
	docker logs -f $(CONTAINER)

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

backend-lint: ## Lint and typecheck the backend (ruff + ty)
	cd backend && uv run ruff check && uv run ty check

frontend-run: ## Run the Vite dev server on 127.0.0.1:5173 (needs server-run)
	cd frontend && pnpm dev

frontend-test: ## Run the frontend unit tests (Vitest)
	cd frontend && pnpm test

frontend-e2e: ## Run the frontend end-to-end tests (Playwright)
	cd frontend && pnpm test:e2e

frontend-lint: ## Typecheck the frontend (vue-tsc)
	cd frontend && pnpm typecheck

test: backend-test frontend-test ## Run all test suites

lint: backend-lint frontend-lint ## Lint and typecheck the whole project
