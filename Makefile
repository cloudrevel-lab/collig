.PHONY: help install up down dev core frontend pa list-sessions lint console-start console-stop console-status

help:
	@echo "Available commands:"
	@echo "  make install       - Install core (using uv) and frontend dependencies"
	@echo "  make up            - Start both core and frontend services"
	@echo "  make dev           - Alias for 'make up'"
	@echo "  make down          - Instructions to stop services"
	@echo "  make core          - Start only the core service"
	@echo "  make frontend      - Start only the frontend service"
	@echo "  make pa            - Start the interactive CLI co-worker"
	@echo "                       Usage: make pa [session=SESSION_ID] [prompt=\"PROMPT\"]"
	@echo "  make list-sessions - List available chat sessions"
	@echo "  make lint          - Run isort, black, and flake8 on modified files (max line length 120)"
	@echo "  make console-start - Start the admin console on port 5005"
	@echo "  make console-stop  - Stop the admin console"
	@echo "  make console-status- Check admin console status"

install:
	cd core && uv venv && uv sync
	cd frontend && npm install

core:
	cd core && uv run uvicorn main:app --reload

frontend:
	cd frontend && npm run dev

pa:
	cd core && uv run python cli.py $(if $(session),--session $(session),) $(if $(prompt),--prompt "$(prompt)",)

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

# ─── Admin Console ─────────────────────────────────────────────────────────────

console-build:
	cd frontend && npm run build

console-start: console-build
	@echo "Starting admin console on http://localhost:5005 (with auto-reload) ..."
	cd core && uv run uvicorn main:app --host 0.0.0.0 --port 5005 --reload &
	@echo "Admin console started: http://localhost:5005/admin"

console-stop:
	@-lsof -ti:5005 | xargs kill 2>/dev/null || echo "No console process found on port 5005"
	@rm -f ~/.collig/console.pid
	@echo "Admin console stopped."

console-status:
	@if lsof -ti:5005 > /dev/null 2>&1; then \
		echo "● Admin console is running on http://localhost:5005/admin"; \
		lsof -ti:5005; \
	else \
		echo "○ Admin console is not running"; \
	fi
