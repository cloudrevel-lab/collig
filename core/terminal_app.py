"""
Standalone terminal-only web application.

Run with:

    uv run uvicorn core.terminal_app:app --host 0.0.0.0 --port 5006

It exposes only:

* /health
* /api/terminal/bootstrap, /api/terminal/sessions, /api/terminal/ws
* /api/terminal/llm/... (used by the per-session relay)
* the built terminal-only SPA in frontend/dist-terminal

There is deliberately no /api/chat, /api/config, /api/bookmarks, skill toggle or
admin surface here.  The full console remains available via core.main.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from core.terminal_routes import router

DEFAULT_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist-terminal"


def _default_dist() -> Path:
    raw = os.environ.get("COLLIG_TERMINAL_DIST") or str(DEFAULT_DIST)
    return Path(raw).expanduser().resolve()


def create_app(dist_dir: str | Path | None = None) -> FastAPI:
    dist = Path(dist_dir).expanduser().resolve() if dist_dir is not None else _default_dist()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        from core.terminal import get_terminal_manager

        manager = get_terminal_manager()
        ready, reason = manager.readiness()
        if ready:
            print("[terminal-app] sandbox ready", flush=True)
        else:
            print("[terminal-app] sandbox NOT ready: " + reason, flush=True)
        if not os.environ.get("COLLIG_TERMINAL_TOKEN"):
            print(
                "[terminal-app] COLLIG_TERMINAL_TOKEN is not set. Loopback pages can bootstrap; "
                "remote users cannot obtain the generated token. Set it for a shared server.",
                flush=True,
            )
        yield

    app = FastAPI(
        title="Collig Terminal",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(router)

    @app.get("/health")
    def health():
        return {"status": "ok", "app": "collig-terminal"}

    index = dist / "terminal.html"
    if index.is_file():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/")
        @app.get("/{path:path}")
        async def serve_terminal(path: str = ""):
            if path.startswith("api/") or path.startswith("assets/"):
                raise HTTPException(status_code=404, detail="Not found")
            candidate = (dist / path).resolve() if path else index
            try:
                candidate.relative_to(dist)
            except ValueError:
                raise HTTPException(status_code=404, detail="Not found")
            if candidate.is_file():
                return FileResponse(candidate)
            # The terminal SPA has no client-side routes, but this keeps a
            # stray path such as /terminal from showing a bare 404.
            return FileResponse(index)

    else:

        @app.get("/")
        def missing_build():
            return HTMLResponse(
                "<h1>Collig Terminal</h1><p>The terminal frontend has not been built.</p>"
                "<p>Run <code>make terminal-app</code> (or "
                "<code>cd frontend &amp;&amp; npm run build:terminal</code>), then restart.</p>",
                status_code=503,
            )

    return app


app = create_app()
