"""
Terminal HTTP and WebSocket routes.

These live in a router rather than in core/main.py because the same surface is
served by two applications:

* the full admin console (core.main), alongside chat/notes/config/etc.;
* the standalone terminal-only deployment (core.terminal_app), which exposes
  nothing else.

Keeping one router means the security checks (token, Origin, one-shot ticket,
per-session proxy) cannot drift between the two deployments.
"""

from __future__ import annotations

import asyncio
import json as _json
import threading
import time

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.runtime import get_llm_config, load_config, provider_base_url
from core.terminal import TerminalUnavailable, get_terminal_manager

router = APIRouter()


def _terminal_token_from_request(request: Request) -> str:
    token = request.headers.get("x-collig-terminal-token", "")
    if token:
        return token.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _terminal_origin_ok(request: Request) -> bool:
    """Reject a cross-site browser request; allow non-browser clients (curl).

    The token is sent in a custom header on every terminal HTTP call, so a
    cross-site form cannot perform it anyway.  This is defence in depth.
    """
    origin = request.headers.get("origin")
    if not origin:
        return True
    return get_terminal_manager().origin_allowed(origin, request.headers.get("host"))


def _terminal_proxy_port(request: Request) -> int:
    mgr = get_terminal_manager()
    if mgr.settings.proxy_port:
        return int(mgr.settings.proxy_port)
    if request.url.port:
        return int(request.url.port)
    return 443 if request.url.scheme == "https" else 80


class _TerminalCreatePydantic(BaseModel):
    cols: int = 120
    rows: int = 32
    # Optional existing web-chat session to resume inside the terminal.
    session_id: str | None = None


@router.get("/api/terminal/bootstrap")
def terminal_bootstrap(request: Request):
    """Describe the terminal and, on loopback only, reveal the local token."""
    mgr = get_terminal_manager()
    status = mgr.status()
    local = mgr.bootstrap_allowed(
        request.client.host if request.client else None,
        {str(k).lower(): v for k, v in request.headers.items()},
    )
    # Do not let a cross-origin page read the loopback token.  Browsers send
    # Origin on cross-origin fetches; checking it here keeps the token out of
    # the response even when the server's CORS policy is permissive.
    origin = request.headers.get("origin")
    if origin and not mgr.origin_allowed(origin, request.headers.get("host")):
        local = False
    return {
        **status,
        "token": mgr.token if (local and mgr.settings.enabled) else None,
        "local": local,
        "auth_required": not local,
        "docs": "Use make terminal-image once, then open the Terminal page.",
    }


@router.post("/api/terminal/sessions")
def create_terminal_session(request: Request, body: _TerminalCreatePydantic = _TerminalCreatePydantic()):
    mgr = get_terminal_manager()
    if not _terminal_origin_ok(request):
        raise HTTPException(status_code=403, detail="origin not allowed")
    if not mgr.authorize(_terminal_token_from_request(request)):
        raise HTTPException(status_code=401, detail="terminal access token required")
    try:
        created = mgr.create_session(
            proxy_port=_terminal_proxy_port(request),
            requested_session_id=body.session_id,
        )
    except Exception as exc:
        status = 503 if isinstance(exc, TerminalUnavailable) else 429
        raise HTTPException(status_code=status, detail=str(exc))
    return created


@router.post("/api/terminal/sessions/{session_id}/ticket")
def terminal_ticket(session_id: str, request: Request):
    mgr = get_terminal_manager()
    if not _terminal_origin_ok(request):
        raise HTTPException(status_code=403, detail="origin not allowed")
    if not mgr.authorize(_terminal_token_from_request(request)):
        raise HTTPException(status_code=401, detail="terminal access token required")
    try:
        return mgr.issue_ticket(session_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/api/terminal/sessions/{session_id}")
def delete_terminal_session(session_id: str, request: Request):
    mgr = get_terminal_manager()
    if not _terminal_origin_ok(request):
        raise HTTPException(status_code=403, detail="origin not allowed")
    if not mgr.authorize(_terminal_token_from_request(request)):
        raise HTTPException(status_code=401, detail="terminal access token required")
    session = mgr.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="terminal session not found")
    mgr.release(session)
    return {"message": "terminal session closed"}


@router.websocket("/api/terminal/ws")
async def terminal_websocket(websocket: WebSocket):
    mgr = get_terminal_manager()
    if not mgr.settings.enabled:
        await websocket.close(code=1008, reason="terminal disabled")
        return
    if not mgr.origin_allowed(websocket.headers.get("origin"), websocket.headers.get("host")):
        await websocket.close(code=1008, reason="origin not allowed")
        return
    session = mgr.consume_ticket(websocket.query_params.get("ticket"))
    if session is None or not mgr.mark_connected(session):
        await websocket.close(code=1008, reason="invalid or expired ticket")
        return

    await websocket.accept()

    try:
        cols = max(20, min(int(websocket.query_params.get("cols") or 120), 500))
        rows = max(5, min(int(websocket.query_params.get("rows") or 32), 200))
    except ValueError:
        cols, rows = 120, 32

    try:
        proc = await asyncio.to_thread(mgr.spawn, session, cols, rows)
    except Exception as exc:
        try:
            await websocket.send_text(_json.dumps({"type": "error", "message": str(exc)}))
            await websocket.close(code=1011)
        except Exception:
            pass
        await asyncio.to_thread(mgr.release, session)
        return

    loop = asyncio.get_running_loop()
    # Bound the server-side buffer: a user can run "!yes" and produce output
    # faster than the browser consumes it.  Dropping under flood keeps the
    # server alive; the container's own memory/CPU limits bound the producer.
    output: asyncio.Queue = asyncio.Queue(maxsize=512)

    def _push(item) -> None:
        try:
            output.put_nowait(item)
        except asyncio.QueueFull:
            pass

    def _reader() -> None:
        while True:
            try:
                data = proc.read()
            except OSError:
                break
            if not data:
                break
            try:
                loop.call_soon_threadsafe(_push, data)
            except RuntimeError:
                break
        try:
            loop.call_soon_threadsafe(_push, None)
        except RuntimeError:
            pass

    threading.Thread(target=_reader, name=f"collig-term-{session.id}", daemon=True).start()

    async def _pump_output() -> None:
        while True:
            try:
                item = await asyncio.wait_for(output.get(), timeout=5.0)
            except asyncio.TimeoutError:
                if time.time() - session.last_activity > mgr.settings.idle_timeout:
                    await websocket.send_text(_json.dumps({"type": "timeout"}))
                    return
                continue
            if item is None:
                await websocket.send_text(_json.dumps({"type": "exit"}))
                return
            await websocket.send_bytes(item)
            session.touch()

    async def _receive_input() -> None:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message["type"] != "websocket.receive":
                continue
            data = message.get("bytes")
            if data:
                if len(data) <= 64 * 1024:
                    await asyncio.to_thread(proc.write, data)
                    session.touch()
                continue
            text = message.get("text")
            if not text or len(text) > 64 * 1024:
                continue
            try:
                payload = _json.loads(text)
            except ValueError:
                await asyncio.to_thread(proc.write, text.encode("utf-8"))
                session.touch()
                continue
            kind = str(payload.get("type") or "")
            if kind == "input":
                await asyncio.to_thread(proc.write, str(payload.get("data") or "").encode("utf-8"))
                session.touch()
            elif kind == "resize":
                try:
                    await asyncio.to_thread(
                        proc.resize,
                        int(payload.get("cols") or cols),
                        int(payload.get("rows") or rows),
                    )
                except (TypeError, ValueError):
                    pass
            elif kind == "ping":
                await websocket.send_text(_json.dumps({"type": "pong"}))
            elif kind == "close":
                return

    output_task = asyncio.create_task(_pump_output())
    input_task = asyncio.create_task(_receive_input())
    try:
        _, pending = await asyncio.wait({output_task, input_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
        await asyncio.to_thread(mgr.release, session)


@router.api_route("/api/terminal/llm/{proxy_token}/{path:path}", methods=["GET", "POST"])
async def terminal_llm_proxy(proxy_token: str, path: str, request: Request):
    """Provider-credential-injecting proxy used only by sandboxed terminals.

    The sandbox holds a disposable per-session token, never the real provider
    key.  This endpoint is reachable only through the per-session relay, which
    forwards just the four paths listed below.
    """
    mgr = get_terminal_manager()
    session = mgr.find_by_proxy_token(proxy_token)
    if session is None:
        raise HTTPException(status_code=404, detail="terminal session not found")
    if not path.startswith("v1/"):
        raise HTTPException(status_code=404, detail="not found")
    sub_path = path[3:].strip("/")
    if sub_path not in {"chat/completions", "completions", "embeddings", "models"}:
        raise HTTPException(status_code=404, detail="not found")
    if not mgr.allow_proxy_request(session):
        raise HTTPException(status_code=429, detail="terminal LLM rate limit exceeded")

    import httpx

    cfg = load_config()
    llm = get_llm_config(cfg)
    provider = str(llm.get("provider") or "openai").lower()
    base_url = provider_base_url(provider, cfg)
    if not base_url:
        raise HTTPException(status_code=503, detail=f"provider {provider!r} has no base URL")
    upstream_url = base_url.rstrip("/") + "/" + sub_path

    body = await request.body()
    headers = {}
    for key, value in request.headers.items():
        lowered = key.lower()
        if lowered in {"host", "authorization", "content-length", "connection", "origin", "referer"}:
            continue
        headers[key] = value
    api_key = str(llm.get("api_key") or "")
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    headers["accept-encoding"] = "identity"

    if body and sub_path in {"chat/completions", "completions"}:
        try:
            payload = _json.loads(body)
            payload["model"] = str(llm.get("llm_model") or payload.get("model") or "")
            body = _json.dumps(payload).encode("utf-8")
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="invalid JSON body")

    client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=20.0), follow_redirects=False)
    try:
        upstream_request = client.build_request(request.method, upstream_url, headers=headers, content=body)
        upstream = await client.send(upstream_request, stream=True)
    except Exception as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"provider request failed: {exc}")

    async def _stream():
        try:
            async for chunk in upstream.aiter_bytes():
                if chunk:
                    yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    response_headers = {}
    for key in ("content-type", "cache-control", "openai-processing-ms", "x-request-id"):
        if key in upstream.headers:
            response_headers[key] = upstream.headers[key]
    return StreamingResponse(
        _stream(),
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type"),
    )
