# summon-claude Development Makefile
#
# Common tasks for development workflow.
#
# Lint targets auto-fix and fail if files were modified (for CI/hooks).

CURRENT_BRANCH := $(shell git branch --show-current)

.PHONY: help install lint test clean all

# Default target - auto-generated from inline ## comments
help:
	@echo "summon-claude Development Commands ($(CURRENT_BRANCH))"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install all dependencies (uv sync)
	uv sync

lint: ## Run all linters (auto-fix ruff check + format, then pyright)
	@echo "Running ruff check (auto-fix)..."
	uv run ruff check . --fix --exit-non-zero-on-fix
	@echo "Running ruff format (auto-fix)..."
	uv run ruff format . --exit-non-zero-on-format
	@echo "Running pyright..."
	uv run pyright

test: ## Run test suite
	@echo "Running pytest..."
	uv run pytest tests/ -v

clean: ## Remove cache files
	rm -rf .cache

all: install lint test ## Complete workflow: install → lint → test
