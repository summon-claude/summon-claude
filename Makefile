# summon-claude Development Makefile
#
# Common tasks for development workflow.
#
# Lint targets auto-fix and fail if files were modified (for CI/hooks).

CURRENT_BRANCH := $(shell git branch --show-current)

.PHONY: help
.PHONY: install lint test build clean all
.PHONY: py-install py-lint py-typecheck py-test py-test-quick py-build py-clean py-all
.PHONY: repo-hooks-install repo-hooks-clean

# Default target - auto-generated from inline ## comments
help:
	@echo "summon-claude Development Commands ($(CURRENT_BRANCH))"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ============================================================================
# CORE TARGETS
# ============================================================================

install: py-install repo-hooks-install ## Install all dependencies

lint: py-lint ## Run all linters (auto-fix + verify)

test: py-test ## Run all tests

clean: py-clean repo-hooks-clean ## Remove all build artifacts

all: py-all ## Complete workflow: install → lint → test

# ============================================================================
# PYTHON
# ============================================================================

py-install: ## Install Python dependencies
	uv sync

py-lint: ## Lint Python (auto-fix ruff check + format)
	@echo "Running ruff check (auto-fix)..."
	uv run ruff check . --fix --exit-non-zero-on-fix
	@echo "Running ruff format (auto-fix)..."
	uv run ruff format . --exit-non-zero-on-format

py-typecheck: ## Run pyright type checking
	@echo "Running pyright..."
	uv run pyright

py-test: ## Run full Python test suite
	@echo "Running pytest..."
	uv run pytest tests/ -v

py-test-quick: ## Run quick Python tests (exclude slow, fail-fast)
	@echo "Running quick pytest..."
	uv run pytest --maxfail=1 -q -m "not slow"

py-build: ## Build sdist and wheel
	uv build

py-clean: ## Remove Python cache files
	rm -rf .cache dist

py-all: py-install py-lint py-test ## Python workflow: install → lint → test

# ============================================================================
# REPO HOOKS
# ============================================================================

repo-hooks-install: ## Install git hooks (prek)
	uvx prek auto-update
	uvx prek install --install-hooks

repo-hooks-clean: ## Remove git hooks and cache
	uvx prek uninstall || true
	uvx prek cache clean
