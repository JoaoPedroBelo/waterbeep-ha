# Makefile for the Waterbeep Home Assistant Integration

.PHONY: help install lint format test coverage clean pre-commit check fix

help:
	@echo "Waterbeep Development Commands:"
	@echo ""
	@echo "  make install       Install development dependencies"
	@echo "  make lint          Run all linters (ruff, mypy)"
	@echo "  make format        Auto-format code with ruff"
	@echo "  make test          Run all tests"
	@echo "  make coverage      Run tests with coverage report"
	@echo "  make clean         Remove generated files"
	@echo "  make pre-commit    Install pre-commit hooks"
	@echo "  make check         Run all checks (lint + test)"
	@echo "  make fix           Auto-fix common issues"
	@echo ""

install:
	pip install -r requirements-dev.txt

lint:
	@echo "Running Ruff linter..."
	ruff check custom_components/ tests/
	@echo ""
	@echo "Checking code formatting..."
	ruff format custom_components/ tests/ --check
	@echo ""
	@echo "Running MyPy type checker..."
	mypy custom_components/waterbeep --show-error-codes --pretty

format:
	@echo "Formatting code with Ruff..."
	ruff check custom_components/ tests/ --fix
	ruff format custom_components/ tests/
	@echo "✓ Code formatted!"

test:
	@echo "Running tests..."
	pytest tests/ -v

coverage:
	@echo "Running tests with coverage..."
	pytest tests/ --cov=custom_components.waterbeep --cov-report=html --cov-report=term-missing
	@echo ""
	@echo "Coverage report generated in htmlcov/index.html"

clean:
	@echo "Cleaning up..."
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	@echo "✓ Cleaned!"

pre-commit:
	@echo "Installing pre-commit hooks..."
	pre-commit install
	@echo "✓ Pre-commit hooks installed!"

check: lint test
	@echo ""
	@echo "✓ All checks passed!"

fix:
	@echo "Auto-fixing common issues..."
	ruff check custom_components/ tests/ --fix
	ruff format custom_components/ tests/
	@echo "✓ Fixed!"
