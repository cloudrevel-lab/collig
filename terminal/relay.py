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

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

ALLOWED_PATHS = {
    "chat/completions",
    "completions",
    "embeddings",
    "models",
}

TARGET = (os.environ.get("COLLIG_TERMINAL_RELAY_TARGET") or "").rstrip("/")
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


if __name__ == "__main__":
    uvicorn.run(
        app, host="0.0.0.0", port=int(os.environ.get("COLLIG_TERMINAL_RELAY_PORT", "8080")), log_level="warning"
    )
