# =============================================================================
# Makefile - Azure ML CI/CD Pipeline
# =============================================================================
# Author: Gabriel Demetrios Lafis
# =============================================================================

.PHONY: help install lint format test test-unit test-integration coverage \
        docker-build docker-test docker-lint clean infra-validate

PYTHON := python
PIP := pip
PYTEST := $(PYTHON) -m pytest
RUFF := ruff
MYPY := mypy

# =============================================================================
# Help
# =============================================================================

help: ## Show this help message
	@echo "Azure ML CI/CD Pipeline - Available Commands"
	@echo "============================================="
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# =============================================================================
# Setup
# =============================================================================

install: ## Install all dependencies
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install ruff mypy pytest pytest-cov pytest-asyncio

install-dev: ## Install development dependencies
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install ruff mypy pytest pytest-cov pytest-asyncio pre-commit

# =============================================================================
# Code Quality
# =============================================================================

lint: ## Run linter checks
	$(RUFF) check src/ tests/

format: ## Format code with Ruff
	$(RUFF) format src/ tests/

format-check: ## Check code formatting
	$(RUFF) format --check src/ tests/

typecheck: ## Run MyPy type checking
	$(MYPY) src/ --ignore-missing-imports

quality: lint format-check typecheck ## Run all code quality checks

# =============================================================================
# Testing
# =============================================================================

test: ## Run all tests
	$(PYTEST) tests/ -v --tb=short

test-unit: ## Run unit tests only
	$(PYTEST) tests/unit/ -v --tb=short

test-integration: ## Run integration tests only
	$(PYTEST) tests/integration/ -v --tb=short

coverage: ## Run tests with coverage report
	$(PYTEST) tests/ -v --tb=short \
		--cov=src \
		--cov-report=term-missing \
		--cov-report=html:htmlcov \
		--cov-report=xml:coverage.xml

# =============================================================================
# Docker
# =============================================================================

docker-build: ## Build Docker image
	docker compose -f docker/docker-compose.yml build pipeline

docker-test: ## Run tests in Docker
	docker compose -f docker/docker-compose.yml --profile test run --rm test-runner

docker-lint: ## Run linter in Docker
	docker compose -f docker/docker-compose.yml --profile lint run --rm lint-runner

docker-up: ## Start pipeline container
	docker compose -f docker/docker-compose.yml up -d pipeline

docker-down: ## Stop all containers
	docker compose -f docker/docker-compose.yml down

# =============================================================================
# Infrastructure
# =============================================================================

infra-validate: ## Validate Bicep templates
	az bicep build --file infra/bicep/main.bicep --stdout > /dev/null
	@echo "Bicep validation passed."

infra-deploy-dev: ## Deploy infrastructure to dev
	az deployment group create \
		--resource-group rg-ml-dev \
		--template-file infra/bicep/main.bicep \
		--parameters environment=dev

infra-deploy-staging: ## Deploy infrastructure to staging
	az deployment group create \
		--resource-group rg-ml-staging \
		--template-file infra/bicep/main.bicep \
		--parameters environment=staging

infra-deploy-prod: ## Deploy infrastructure to prod
	az deployment group create \
		--resource-group rg-ml-prod \
		--template-file infra/bicep/main.bicep \
		--parameters environment=prod

# =============================================================================
# Cleanup
# =============================================================================

clean: ## Remove build artifacts and caches
	rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache
	rm -rf htmlcov coverage.xml test-results.xml
	rm -rf evaluation_artifacts promotion_audit logs
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
