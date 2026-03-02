.PHONY: help install up down dev core frontend pa list-sessions lint

help:
	@echo "Available commands:"
	@echo "  make install       - Install core (using uv) and frontend dependencies"
	@echo "  make up            - Start both core and frontend services"
	@echo "  make dev           - Alias for 'make up'"
	@echo "  make down          - Instructions to stop services"
	@echo "  make core          - Start only the core service"
	@echo "  make frontend      - Start only the frontend service"
	@echo "  make pa            - Start the interactive CLI co-worker"
	@echo "                       Usage: make pa [session=SESSION_ID]"
	@echo "  make list-sessions - List available chat sessions"
	@echo "  make lint          - Run isort, black, and flake8 on modified files (max line length 120)"

install:
	cd core && uv venv && uv sync
	cd frontend && npm install

core:
	cd core && uv run uvicorn main:app --reload

frontend:
	cd frontend && npm run dev

pa:
	cd core && uv run python cli.py $(if $(session),--session $(session),)

list-sessions:
	cd core && uv run python list_sessions.py

lint:
	uv run isort --check-only --diff skills/lunar_calendar/__init__.py
	uv run black --check --diff --line-length 120 skills/lunar_calendar/__init__.py
	uv run flake8 --max-line-length 120 skills/lunar_calendar/__init__.py

up:
	@echo "Starting services..."
	@make -j 2 core frontend

dev: up

down:
	@echo "Stopping services... (Please use Ctrl+C to stop the 'make up' process)"
