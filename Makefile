.PHONY: help install up down dev core frontend pa list-sessions lint console-start console-stop console-status console-build

# ─── Port helpers (macOS / Linux via lsof) ─────────────────────────────────────
# These helpers try the preferred port first; if occupied, scan upward up to 100 ports.
# Callers can override via env vars: CORE_PORT, VITE_PORT, CONSOLE_PORT.

MAX_TRIES := 100

find_free_port = $(shell \
	start=$(1); \
	p=$$start; \
	i=0; \
	while lsof -iTCP:$$p -sTCP:LISTEN -t >/dev/null 2>&1; do \
		p=$$((p + 1)); \
		i=$$((i + 1)); \
		if [ $$i -ge $(MAX_TRIES) ]; then \
			echo "ERROR: no free TCP port near $$start" >&2; exit 1; \
		fi; \
	done; \
	echo $$p)

CONSOLE_PORT_FILE := ~/.collig/console.port
DEV_PORTS_FILE := ~/.collig/dev.ports

CORE_PREFERRED ?= 8000
VITE_PREFERRED ?= 5173
CONSOLE_PREFERRED ?= 5005

# If env override is set and free, use it; otherwise pick a free one near preferred.
define resolve_port
$(if $(filter 1,$(shell lsof -iTCP:$(1) -sTCP:LISTEN -t >/dev/null 2>&1 && echo 1 || echo 0)),$(call find_free_port,$(1)),$(1))
endef

help:
	@echo "Available commands:"
	@echo "  make install       - Install core (using uv) and frontend dependencies"
	@echo "  make up            - Start both core (API) and frontend (Vite HMR) dev services"
	@echo "                         Auto-picks free ports near $(CORE_PREFERRED) / $(VITE_PREFERRED)."
	@echo "                         Override with: CORE_PORT=8001 VITE_PORT=5174 make up"
	@echo "  make dev           - Alias for 'make up'"
	@echo "  make down          - Instructions to stop services"
	@echo "  make core          - Start only the core API service"
	@echo "  make frontend      - Start only the frontend (Vite dev server)"
	@echo "  make pa            - Start the interactive CLI co-worker"
	@echo "                         Usage: make pa [session=SESSION_ID] [prompt=\"PROMPT\"]"
	@echo "  make list-sessions - List available chat sessions"
	@echo "  make lint          - Run isort, black, and flake8 on modified files (max line length 120)"
	@echo "  make console-build - Rebuild the frontend bundle"
	@echo "  make console-start - Build + start Collig web (single server, built-in SPA)"
	@echo "                         Runs on $(CONSOLE_PREFERRED) or first free port above."
	@echo "                         Override with: CONSOLE_PORT=5006 make console-start"
	@echo "  make console-stop  - Stop Collig web (reads port from $(CONSOLE_PORT_FILE))"
	@echo "  make console-status- Check Collig web status"

install:
	uv sync
	cd frontend && npm install

core:
	@if [ -n "$$CORE_PORT" ]; then \
		PORT=$$CORE_PORT; \
		if lsof -iTCP:$$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then \
			echo "CORE_PORT $$PORT is in use — picking a free port near $(CORE_PREFERRED)"; \
			PORT=$(call find_free_port,$(CORE_PREFERRED)); \
		fi; \
	else \
		PORT=$(call resolve_port,$(CORE_PREFERRED)); \
	fi; \
	echo "[core] Starting API on http://localhost:$$PORT  (override with CORE_PORT=)"; \
	mkdir -p ~/.collig; \
	echo "core=$$PORT" > $(DEV_PORTS_FILE); \
	uv run uvicorn core.main:app --host 0.0.0.0 --port $$PORT \
		--reload --reload-dir core --reload-dir agents --reload-dir skills

frontend:
	@if [ -n "$$VITE_PORT" ]; then \
		VPORT=$$VITE_PORT; \
		if lsof -iTCP:$$VPORT -sTCP:LISTEN -t >/dev/null 2>&1; then \
			echo "VITE_PORT $$VPORT is in use — picking a free port near $(VITE_PREFERRED)"; \
			VPORT=$(call find_free_port,$(VITE_PREFERRED)); \
		fi; \
	else \
		VPORT=$(call resolve_port,$(VITE_PREFERRED)); \
	fi; \
	CORE_PORT_STORED=$$( [ -f $(DEV_PORTS_FILE) ] && grep ^core= $(DEV_PORTS_FILE) | cut -d= -f2 || echo $(CORE_PREFERRED) ); \
	if lsof -iTCP:$$CORE_PORT_STORED -sTCP:LISTEN -t >/dev/null 2>&1; then \
		: "core is reachable on $$CORE_PORT_STORED"; \
	else \
		CORE_PORT_STORED=$(CORE_PREFERRED); \
	fi; \
	echo "[frontend] Vite dev server: http://localhost:$$VPORT  (proxies /api → http://localhost:$$CORE_PORT_STORED)"; \
	VITE_PORT=$$VPORT VITE_API_PROXY=http://localhost:$$CORE_PORT_STORED sh -c 'cd frontend && npm run dev -- --host 0.0.0.0 --port $$VITE_PORT'

pa:
	uv run python core/cli.py $(if $(session),--session $(session),) $(if $(prompt),--prompt "$(prompt)",)

list-sessions:
	uv run python core/list_sessions.py

lint:
	uv run isort --check-only --diff skills/lunar_calendar/__init__.py
	uv run black --check --diff --line-length 120 skills/lunar_calendar/__init__.py
	uv run flake8 --max-line-length 120 skills/lunar_calendar/__init__.py

up:
	@echo "Starting services (auto port selection)..."
	@# Compute both ports up-front so the frontend's proxy can target the chosen core port.
	@CORE_PORT_USE=$$( if [ -n "$$CORE_PORT" ] && ! lsof -iTCP:$$CORE_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then echo $$CORE_PORT; else echo $(call resolve_port,$(CORE_PREFERRED)); fi ); \
	 VITE_PORT_USE=$$( if [ -n "$$VITE_PORT" ] && ! lsof -iTCP:$$VITE_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then echo $$VITE_PORT; else echo $(call resolve_port,$(VITE_PREFERRED)); fi ); \
	 echo ""; \
	 echo "● Core API:      http://localhost:$$CORE_PORT_USE"; \
	 echo "● Frontend (dev): http://localhost:$$VITE_PORT_USE   (/api proxies to core)"; \
	 echo ""; \
	 mkdir -p ~/.collig; \
	 printf "core=%s\nvite=%s\n" $$CORE_PORT_USE $$VITE_PORT_USE > $(DEV_PORTS_FILE); \
	 $(MAKE) -j 2 _core_with_port CORE_PORT_RUN=$$CORE_PORT_USE _frontend_with_port VITE_PORT_RUN=$$VITE_PORT_USE CORE_PORT_RUN=$$CORE_PORT_USE

_core_with_port:
	@echo "[core] binding port $(CORE_PORT_RUN) — auto-reloading core/, agents/, skills/"
	@uv run uvicorn core.main:app --host 0.0.0.0 --port $(CORE_PORT_RUN) \
		--reload --reload-dir core --reload-dir agents --reload-dir skills

_frontend_with_port:
	@echo "[frontend] binding port $(VITE_PORT_RUN); proxying /api to core port $(CORE_PORT_RUN) — HMR auto-reloads on save"
	@VITE_PORT=$(VITE_PORT_RUN) VITE_API_PROXY=http://localhost:$(CORE_PORT_RUN) sh -c 'cd frontend && npm run dev -- --host 0.0.0.0 --port $$VITE_PORT'

# Watches frontend/src and rebuilds frontend/dist on every change. FastAPI's
# StaticFiles mount re-reads dist/ on each request, so a browser refresh picks
# up the new bundle immediately. Used by console-start so the single-server
# path also gets live reload (without needing a separate Vite
# dev server port).
_console_frontend_watch:
	@echo "[frontend-watch] rebuilding frontend/dist whenever src/ changes — refresh / to pick up updates"
	@cd frontend && npx vite build --watch --mode development 2>&1 | awk '$$0 ~ /built in|error|watching/ {print "[frontend-watch] "$$0} !/built in|error|watching/ {next}'

dev: up

down:
	@echo "Stopping services... (Please use Ctrl+C to stop the 'make up' process)"
	@echo "Or kill by ports stored in $(DEV_PORTS_FILE):"
	@-if [ -f $(DEV_PORTS_FILE) ]; then \
		while IFS='=' read -r svc port; do \
			[ -z "$$port" ] && continue; \
			echo "  killing $$svc on port $$port"; \
			lsof -ti:$$port | xargs -r kill 2>/dev/null || true; \
		done < $(DEV_PORTS_FILE); \
		rm -f $(DEV_PORTS_FILE); \
	fi

# ─── Collig Web (single server, built SPA served from FastAPI) ──────────────

console-build:
	cd frontend && npm run build

console-start: console-build
	@mkdir -p ~/.collig
	@if [ -n "$$CONSOLE_PORT" ]; then \
		CP=$$CONSOLE_PORT; \
		if lsof -iTCP:$$CP -sTCP:LISTEN -t >/dev/null 2>&1; then \
			echo "CONSOLE_PORT $$CP is in use — picking a free port near $(CONSOLE_PREFERRED)"; \
			CP=$(call find_free_port,$(CONSOLE_PREFERRED)); \
		fi; \
	else \
		CP=$(call resolve_port,$(CONSOLE_PREFERRED)); \
	fi; \
	echo ""; \
	echo "● Starting Collig (single-server mode)..."; \
	if [ $$CP != $(CONSOLE_PREFERRED) ]; then echo "  (port $(CONSOLE_PREFERRED) was occupied, using $$CP)"; fi; \
	echo "  UI:  http://localhost:$$CP/   (refresh to pick up frontend rebuilds)"; \
	echo "  API: http://localhost:$$CP/api/*"; \
	echo "  Backend auto-reload: core/ agents/ skills/"; \
	echo "  Frontend auto-rebuild: vite build --watch writes to frontend/dist/"; \
	echo ""; \
	echo $$CP > $(CONSOLE_PORT_FILE); \
	$(MAKE) -j 2 _console_uvicorn CONSOLE_PORT_RUN=$$CP _console_frontend_watch

_console_uvicorn:
	@uv run uvicorn core.main:app --host 0.0.0.0 --port $(CONSOLE_PORT_RUN) \
		--reload --reload-dir core --reload-dir agents --reload-dir skills

console-stop:
	@if [ -f $(CONSOLE_PORT_FILE) ]; then \
		CPORT=$$(cat $(CONSOLE_PORT_FILE)); \
		echo "Killing Collig web on port $$CPORT..."; \
		lsof -ti:$$CPORT | xargs -r kill 2>/dev/null || echo "No process on port $$CPORT"; \
		rm -f $(CONSOLE_PORT_FILE) ~/.collig/console.pid; \
	else \
		echo "No $(CONSOLE_PORT_FILE) — trying default port $(CONSOLE_PREFERRED)"; \
		lsof -ti:$(CONSOLE_PREFERRED) | xargs -r kill 2>/dev/null || echo "No console process found on port $(CONSOLE_PREFERRED)"; \
		rm -f ~/.collig/console.pid; \
	fi
	@-pkill -f "vite build --watch" 2>/dev/null || true
	@echo "Collig web stopped."

console-status:
	@if [ -f $(CONSOLE_PORT_FILE) ]; then \
		CPORT=$$(cat $(CONSOLE_PORT_FILE)); \
		if lsof -ti:$$CPORT > /dev/null 2>&1; then \
			echo "● Collig web is running: http://localhost:$$CPORT/  (port stored in $(CONSOLE_PORT_FILE))"; \
			lsof -ti:$$CPORT; \
		else \
			echo "○ Collig web is NOT running (port file says $$CPORT but nothing is listening)"; \
		fi; \
	else \
		if lsof -ti:$(CONSOLE_PREFERRED) > /dev/null 2>&1; then \
			echo "● Collig web is running on default port: http://localhost:$(CONSOLE_PREFERRED)/"; \
			lsof -ti:$(CONSOLE_PREFERRED); \
		else \
			echo "○ Collig web is not running"; \
		fi; \
	fi
