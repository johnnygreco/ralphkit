.DEFAULT_GOAL := help
.PHONY: help install test lint format clean publish

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies
	uv sync

test: ## Run tests with verbose output
	uv run pytest tests/ -v

lint: ## Auto-fix lint issues
	uv run ruff format src/ tests/
	uv run ruff check src/ tests/ --fix --unsafe-fixes

format: ## Auto-format and fix lint issues
	uv run ruff format src/ tests/
	uv run ruff check src/ tests/ --fix --unsafe-fixes

clean: ## Remove build artifacts and caches
	rm -rf build/ dist/ *.egg-info src/*.egg-info .pytest_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

publish: ## Publish a release (usage: make publish VERSION=x.y.z)
	./scripts/publish.sh $(VERSION)
