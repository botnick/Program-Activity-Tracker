# Activity Tracker — convenience wrapper around the project's tooling.
#
# Designed to work in WSL / Git Bash on Windows as well as Linux.
# `run-elevated` shells out to PowerShell because UAC is Windows-only.

PYTHON ?= python
NPM ?= npm

.PHONY: help bootstrap dev test lint format typecheck build run run-elevated clean

help:
	@echo "Targets: bootstrap dev test lint format typecheck build run run-elevated clean"

bootstrap:
	$(PYTHON) -m pip install -e ".[dev]"
	cd ui && $(NPM) ci && $(NPM) run build
	if [ -f mcp/pyproject.toml ]; then $(PYTHON) -m pip install -e ./mcp[dev]; fi

dev:
	$(PYTHON) -m uvicorn backend.app.main:app --reload --port 8000

test:
	$(PYTHON) -m pytest -v

lint:
	$(PYTHON) -m ruff check backend service tests
	cd ui && $(NPM) run lint

format:
	$(PYTHON) -m ruff format backend service tests

typecheck:
	$(PYTHON) -m mypy backend service
	cd ui && $(NPM) run typecheck

build:
	cd ui && $(NPM) run build

run:
	$(PYTHON) -m uvicorn backend.app.main:app --port 8000

run-elevated:
	powershell -ExecutionPolicy Bypass -File run-elevated.ps1

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	rm -rf ui/dist ui/node_modules
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
