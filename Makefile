PYTHON := .venv/bin/python
RUN := PYTHONPATH=src $(PYTHON)
ARGS ?=

.DEFAULT_GOAL := help
.PHONY: help setup up down status sync dataset-export dataset-check eval bench report view test

help: ## Show available targets
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## Install locked dependencies and validate .env
	uv sync --frozen --all-groups
	$(RUN) scripts/check_env.py

up: ## Start Langfuse and the Handy tracing proxy
	$(RUN) scripts/check_env.py
	docker compose up --detach --build

down: ## Stop the stack without deleting volumes
	docker compose down

status: ## Show local stack status
	docker compose ps

sync: ## Bootstrap the dataset and synchronize evaluator/rule
	$(RUN) scripts/wait_for_langfuse.py
	$(RUN) -m transcript_cleanup_bench.sync

dataset-export: ## Refresh the tracked dataset snapshot atomically
	$(RUN) -m transcript_cleanup_bench.dataset export

dataset-check: ## Check the tracked snapshot for Langfuse drift
	$(RUN) -m transcript_cleanup_bench.dataset check

eval: ## Run diagnostic experiments (default concurrency 8)
	$(RUN) -m transcript_cleanup_bench.runner $(ARGS)

bench: ## Publish the full serial 360-execution benchmark
	$(RUN) -m transcript_cleanup_bench.runner --publish $(ARGS)

report: ## Rebuild README from the published summary only
	$(RUN) scripts/report.py

view: ## Open Langfuse in the default browser
	open http://localhost:4001

test: ## Run the test suite
	PYTHONPATH=src .venv/bin/pytest
