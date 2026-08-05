# Pinned promptfoo version — bump deliberately, never track @latest,
# so eval results stay comparable between runs.
PROMPTFOO_VERSION := 0.122.0
PROMPTFOO := npx --yes promptfoo@$(PROMPTFOO_VERSION)

# Extra flags for eval, e.g. make eval ARGS="--filter-pattern mishears"
ARGS ?=

.DEFAULT_GOAL := help
.PHONY: help eval view version install clean

help: ## Show the available targets
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  promptfoo version: $(PROMPTFOO_VERSION)"

eval: ## Run every test against the prompts
	$(PROMPTFOO) eval $(ARGS)

view: ## Open the results grid in a browser
	$(PROMPTFOO) view

version: ## Print the promptfoo version actually being run
	$(PROMPTFOO) --version

install: ## Pre-download the pinned version into the npx cache
	npx --yes promptfoo@$(PROMPTFOO_VERSION) --version

clean: ## Delete cached eval results
	$(PROMPTFOO) cache clear
