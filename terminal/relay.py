"""
Per-session relay sidecar for the web terminal.

The terminal container lives on an internal Docker network with no route to
the host, LAN or Internet.  Its only reachable peer is this relay, which is
attached to both that private network and the normal bridge.  The relay
forwards exactly one fixed upstream prefix:

    /v1/<allowed>  ->  http://host:port/api/terminal/llm/<session-token>/v1/<allowed>

It deliberately does not accept a caller-supplied upstream, so it cannot be
used as an SSRF pivot to /api/config or any other host endpoint.  The main app
still validates the per-session token and injects the provider credential.
"""

from __future__ import annotations

import os
import re

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

ALLOWED_PATHS = {
    "chat/completions",
    "completions",
    "embeddings",
    "models",
}

# The LLM target ends in .../api/terminal/llm/<session-token>; the market
# lives next to it at .../api/terminal/market/<session-token>.  Deriving it
# keeps one token in the environment instead of two.
TARGET = (os.environ.get("COLLIG_TERMINAL_RELAY_TARGET") or "").rstrip("/")
MARKET_TARGET = TARGET.replace("/api/terminal/llm/", "/api/terminal/market/")
# The persona market is fetched by the host, which has an Internet route; the
# sandbox only sees this relay.  Only these two path shapes are forwarded.
MARKET_INDEX = "index.json"
MARKET_FILE_RE = re.compile(r"^personas/[^/]+/(PERSONALITY\.md|meta\.json|sources\.md)$")
app = FastAPI(title="Collig terminal relay", docs_url=None, redoc_url=None, openapi_url=None)


def allowed_path(path: str) -> bool:
    return path.strip("/") in ALLOWED_PATHS


@app.get("/health")
async def health():
    return {"status": "ok", "target_configured": bool(TARGET)}


@app.api_route("/v1/{path:path}", methods=["GET", "POST"])
async def relay(path: str, request: Request):
    if not TARGET:
        return JSONResponse({"error": "relay target is not configured"}, status_code=500)
    if not allowed_path(path):
        return JSONResponse({"error": "not found"}, status_code=404)

    # Cap the body before buffering it.  A browser terminal cannot legitimately
    # send an enormous model request; this also keeps a sandbox from using the
    # relay as a memory-pressure tool.
    body = await request.body()
    if len(body) > 8 * 1024 * 1024:
        return JSONResponse({"error": "request body too large"}, status_code=413)

    upstream_url = TARGET + "/v1/" + path.strip("/")
    headers = {}
    for key, value in request.headers.items():
        lowered = key.lower()
        if lowered in {"host", "authorization", "content-length", "connection", "accept-encoding"}:
            continue
        headers[key] = value
    headers["accept-encoding"] = "identity"

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(300.0, connect=15.0),
        follow_redirects=False,
    )
    try:
        upstream_request = client.build_request(
            request.method,
            upstream_url,
            headers=headers,
            content=body,
        )
        upstream = await client.send(upstream_request, stream=True)
    except Exception as exc:
        await client.aclose()
        return JSONResponse({"error": "upstream unavailable", "detail": str(exc)}, status_code=502)

    async def body_stream():
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
    response_headers["x-collig-terminal-relay"] = "1"
    return StreamingResponse(
        body_stream(),
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type"),
    )


def _market_path_allowed(path: str) -> bool:
    cleaned = path.strip("/")
    if cleaned == MARKET_INDEX:
        return True
    return bool(MARKET_FILE_RE.match(cleaned))


@app.get("/market/{path:path}")
async def market(path: str):
    """Forward the persona market (catalogue + files) to the host proxy.

    The host fetches raw.githubusercontent.com; this sidecar never talks to
    GitHub itself, so it stays a fixed allow-list rather than an open proxy.
    """
    if not MARKET_TARGET:
        return JSONResponse({"error": "relay target is not configured"}, status_code=500)
    if not _market_path_allowed(path):
        return JSONResponse({"error": "not found"}, status_code=404)

    upstream_url = MARKET_TARGET + "/" + path.strip("/")
    client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0), follow_redirects=False)
    try:
        upstream = await client.get(upstream_url, headers={"accept-encoding": "identity"})
    except Exception as exc:
        await client.aclose()
        return JSONResponse({"error": "market upstream unavailable", "detail": str(exc)}, status_code=502)
    content = await upstream.aread()
    await upstream.aclose()
    await client.aclose()
    headers = {"x-collig-terminal-relay": "market"}
    if "content-type" in upstream.headers:
        headers["content-type"] = upstream.headers["content-type"]
    return Response(
        content=content,
        status_code=upstream.status_code,
        headers=headers,
        media_type=upstream.headers.get("content-type", "application/json"),
    )


if __name__ == "__main__":
    uvicorn.run(
        app, host="0.0.0.0", port=int(os.environ.get("COLLIG_TERMINAL_RELAY_PORT", "8080")), log_level="warning"
    )
