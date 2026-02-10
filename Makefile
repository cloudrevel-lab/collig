.PHONY: help install up down dev backend frontend pa list-sessions

help:
	@echo "Available commands:"
	@echo "  make install       - Install backend (using uv) and frontend dependencies"
	@echo "  make up            - Start both backend and frontend services"
	@echo "  make dev           - Alias for 'make up'"
	@echo "  make down          - Instructions to stop services"
	@echo "  make backend       - Start only the backend service"
	@echo "  make frontend      - Start only the frontend service"
	@echo "  make pa            - Start the interactive CLI co-worker"
	@echo "                       Usage: make pa [session=SESSION_ID]"
	@echo "  make list-sessions - List available chat sessions"

install:
	cd backend && uv venv && uv pip install -r requirements.txt
	cd frontend && npm install

backend:
	cd backend && uv run uvicorn main:app --reload

frontend:
	cd frontend && npm run dev

pa:
	cd backend && uv run python cli.py $(if $(session),--session $(session),)

list-sessions:
	cd backend && uv run python list_sessions.py

up:
	@echo "Starting services..."
	@make -j 2 backend frontend

dev: up

down:
	@echo "Stopping services... (Please use Ctrl+C to stop the 'make up' process)"
