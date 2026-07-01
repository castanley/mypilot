# MyPilot — developer convenience targets.
# Podman is first class; override with `make COMPOSE="docker compose" ...`.
COMPOSE ?= podman compose

.PHONY: help install up down logs ps build rebuild api-shell test gen-client sim fmt clean \
        lint test-protocol test-agent test-web ci

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Run the guided installer (checks podman, generates secrets, starts stack)
	./scripts/install.sh

up: ## Start the full stack in the background
	$(COMPOSE) up -d

build: ## Build the api + web images
	$(COMPOSE) build

rebuild: ## Rebuild images without cache and start
	$(COMPOSE) build --no-cache && $(COMPOSE) up -d

down: ## Stop the stack (keep volumes)
	$(COMPOSE) down

logs: ## Tail logs for all services
	$(COMPOSE) logs -f

ps: ## Show service status
	$(COMPOSE) ps

api-shell: ## Open a shell in the api container
	$(COMPOSE) exec mypilot-api bash

test: ## Run backend (api) tests inside the api container
	$(COMPOSE) run --rm mypilot-api pytest -q

lint: ## Lint all Python with ruff + the seam-import style guard (matches CI)
	ruff check .
	python scripts/check_seam_imports.py --selftest
	python scripts/check_seam_imports.py

test-protocol: ## Run the protocol (crypto/signing) tests
	cd mypilot-protocol && python -m pytest

test-agent: ## Run the on-device agent tests (no openpilot needed; imports are lazy)
	cd mypilot-agent && python -m pytest

test-web: ## Run the web typecheck + unit tests
	cd mypilot-web && npm run check && npm test

ci: lint test-protocol test-agent test-web test ## Run the full CI gate locally (lint + all suites)

gen-client: ## Regenerate the typed OpenAPI client for the web app
	./scripts/gen-client.sh

sim: ## Run the simulated device against the running stack
	./scripts/dev-sim-device.sh

clean: ## Stop the stack and remove volumes (DESTRUCTIVE)
	$(COMPOSE) down -v
