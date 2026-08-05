# Pinned promptfoo version — bump deliberately, never track @latest,
# so eval results stay comparable between runs.
PROMPTFOO_VERSION := 0.122.0
PROMPTFOO := npx --yes promptfoo@$(PROMPTFOO_VERSION)

# Extra flags for eval, e.g. make eval ARGS="--filter-pattern mishears"
ARGS ?=

.DEFAULT_GOAL := help
.PHONY: help eval bench report view version install clean

help: ## Show the available targets
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  promptfoo version: $(PROMPTFOO_VERSION)"

eval: ## Run every test against the prompts (fast, concurrent — not for publishing)
	$(PROMPTFOO) eval $(ARGS)

# The published benchmark. Serialised and uncached so the numbers mean something:
# all four models share one inference server, so concurrent requests queue behind
# each other and latency measures scheduling rather than the model. Takes ~12min.
bench: ## Run the publishable benchmark, then regenerate the README
	mkdir -p results
	$(PROMPTFOO) eval --no-cache -j 1 -o results/latest.csv $(ARGS)
	@$(MAKE) --no-print-directory report

report: ## Regenerate the README summary from the last run (no re-run)
	python3 scripts/report.py $(ARGS)

view: ## Open the results grid in a browser
	$(PROMPTFOO) view

version: ## Print the promptfoo version actually being run
	$(PROMPTFOO) --version

install: ## Pre-download the pinned version into the npx cache
	npx --yes promptfoo@$(PROMPTFOO_VERSION) --version

clean: ## Delete cached eval results
	$(PROMPTFOO) cache clear
