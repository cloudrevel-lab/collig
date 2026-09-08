# Debug Session: adk-db-engine
- Status: [OPEN]
- Started: 2026-09-07
- Symptom: Chat turns fail with "I encountered an error: Failed to create database engine for URL 'sqlite:////Users/Jacob.Cui1/.collig/storage/collig.db'"
- Surface: Admin Console Chat view → POST /api/chat → AgentService._ensure_runner → DatabaseSessionService(db_url=...)
- Notes: Relocated path from sessions/adk.db → storage/collig.db but the same ADK DB-engine construction failure persists. The ADK error text is generic and swallows the chained SQLAlchemy/sqlite3 exception.

## Hypotheses (falsifiable)
1. **H1 - SQLite stdlib cannot open that path either** (permissions, ACL, macOS quarantine on ~/.collig/, storage dir owner/group issue, immutable flag, sandbox conflict). If true, stdlib `sqlite3.connect()` fails too.
2. **H2 - File pre-exists in a bad state** (zero bytes from a previous failed open, stale -wal/-shm journal lock, or `adk.db` renamed while a reader held it → SQLAlchemy detects corruption / busy and wraps). If true, listing `storage/` and deleting the file + its journals clears it.
3. **H3 - ADK `DatabaseSessionService` constructor requires specific SQLAlchemy engine kwargs** (e.g. `connect_args={"check_same_thread": False, "timeout": N}` or `future=True`). The black-box default engine creation inside ADK fails for modern SQLAlchemy/sqlite3 combinations unless these are passed.
4. **H4 - URL format / path quirk**: ADK/SQLAlchemy uses a URI constructor that chokes on certain inputs (e.g. path containing a space, or needs `sqlite:////` → vs `sqlite:///` + relative). If true, `os.path.exists()` succeeds but a SQLAlchemy `create_engine()` directly with the same URL fails.
5. **H5 - Missing runtime dep / import side effect**: SQLAlchemy's SQLite dialect tries to import something whose absence is swallowed into the generic "Failed to create database engine" wrapper. If true, a direct `from sqlalchemy import create_engine; create_engine(url).connect()` reproduces with a clearer chained exception.

## Evidence Log
### Experiment 1 — Path/Permission/File precondition check (H1, H2) — RUN 2026-09-07
- Probe script: stdlib `sqlite3.connect(db_path)`, direct `sqlalchemy.create_engine(url)`, and raw `DatabaseSessionService(db_url=...)` run under same interpreter as backend.
- Results:
  - stdlib sqlite3 connect → **PASS** (created DB, wrote row, read it back, DROP'd table). **FALSIFIES H1**.
  - Sync `sqlalchemy.create_engine(url).connect()` on `sqlite:///{path}` → PASS; sqlite_version=3.51.2. **FALSIFIES H2**.
  - `DatabaseSessionService(db_url="sqlite:///{path}")` → **FAILS** with generic `ValueError: Failed to create database engine for URL 'sqlite:///...'`. Chained cause: `sqlalchemy.exc.InvalidRequestError: The asyncio extension requires an async driver to be used. The loaded 'pysqlite' is not async.` Raised at `google/adk/sessions/database_session_service.py:281` inside `create_async_engine(db_url)`.
  - **CONFIRMS H3 + H5** as combined root cause. ADK uses `sqlalchemy.ext.asyncio.create_async_engine` with a plain `sqlite:///` URL which selects the sync pysqlite DBAPI. SQLAlchemy async explicitly rejects this configuration — it requires `aiosqlite` (the async DBAPI driver), and the URL must opt into it.

### Experiment 2 — URL scheme switch (H3/H5 resolution) — RUN 2026-09-07
- Switch URL scheme from `sqlite:///` → `sqlite+aiosqlite:///` and rebuild using same `DatabaseSessionService`.
- Results:
  - `DatabaseSessionService(db_url="sqlite+aiosqlite:///{path}")` → **PASS**, object constructed successfully with `type=DatabaseSessionService`.
  - Also verified via `from core.runner import ADK_DB_PATH` in-process → same success.
  - Note: `aiosqlite` package was already installed in env (v0.22.1) — the missing piece was **not** the package but the **URL scheme selection** (SQLAlchemy async engine was defaulting to pysqlite for plain `sqlite:///` and refusing).
  - Extra: `aiosqlite` now also added to `pyproject.toml` dependencies so fresh installs guarantee it, closing the H5 gap.

### Hypothesis verdicts
- H1: REJECTED (stdlib + sync sqlalchemy both work against identical path/perms)
- H2: REJECTED (no corruption; fresh 0-byte case handled fine by stdlib)
- H3: **CONFIRMED** — engine requires the async DBAPI selection via URL scheme; default pysqlite driver refuses in async context
- H4: REJECTED (absolute 4-slash format `sqlite+aiosqlite:////abs/path` works)
- H5: **PARTIALLY CONFIRMED** — aiosqlite was present locally, but not declared as a project dep; we added it.

## Fix applied (evidence-contingent on H3+H5)
1. `core/runner.py` `_ensure_runner` — switched `DatabaseSessionService(db_url=...)` from `sqlite:///` scheme to `sqlite+aiosqlite:///` so `create_async_engine` picks the correct async DBAPI.
2. `core/runner.py` `ADK_DB_PATH` — file relocated from `~/.collig/sessions/adk.db` → `~/.collig/storage/collig.db` (see previous session), plus `_ensure_runtime_db_location()` auto-migration + storage_dir ensured.
3. `pyproject.toml` — added `aiosqlite>=0.22.0` as a declared dependency so new envs cannot accidentally run with sync-only sqlite DBAPIs.
4. `core/paths.py` — added `storage_dir` and `runtime_db_file` singletons.

## Verification performed
- `python -m py_compile core/runner.py core/main.py core/paths.py` → OK
- In-process probe: `DatabaseSessionService(db_url=sqlite+aiosqlite:/// + ADK_DB_PATH)` → constructed OK.
- `npm run build` (frontend) → OK (previous session)
- Remaining: user must restart backend CLI/web processes (make stop / make start) because `AgentService._runner` is module-scoped singleton booted lazily on first chat turn; new `_ensure_runner` code needs a fresh import.
