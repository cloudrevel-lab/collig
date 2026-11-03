#!/usr/bin/env python3
"""Tests for the standalone terminal-only FastAPI application."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)

passed = []
failed = []


def check(name, cond, detail=""):
    if cond:
        passed.append(name)
        print("PASS: " + name + ((" - " + detail) if detail else ""))
    else:
        failed.append(name)
        print("FAIL: " + name + ((" - " + detail) if detail else ""))


from fastapi.testclient import TestClient  # noqa: E402

from core.terminal_app import create_app  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="collig-terminal-app-test-"))
DIST = TMP / "dist"
(DIST / "assets").mkdir(parents=True)
(DIST / "terminal.html").write_text(
    "<!doctype html><html><body><div id='app'>TERMINAL_TEST_MARKER</div>"
    "<script src='/assets/app.js'></script></body></html>",
    encoding="utf-8",
)
(DIST / "assets" / "app.js").write_text("console.log('terminal')", encoding="utf-8")

client = TestClient(create_app(dist_dir=DIST))

r = client.get("/health")
check("health endpoint is present", r.status_code == 200 and r.json().get("app") == "collig-terminal")

r = client.get("/")
check("root serves the terminal HTML", r.status_code == 200 and "TERMINAL_TEST_MARKER" in r.text)

r = client.get("/assets/app.js")
check("assets are served", r.status_code == 200 and "terminal" in r.text)

r = client.get("/some/client/route")
check("non-API path falls back to terminal HTML", r.status_code == 200 and "TERMINAL_TEST_MARKER" in r.text)

r = client.get("/api/terminal/bootstrap")
check("terminal bootstrap is reachable", r.status_code == 200)

for forbidden in ("/api/config", "/api/chat", "/api/bookmarks", "/api/notes", "/api/stats/tokens"):
    r = client.get(forbidden)
    check("standalone app hides " + forbidden, r.status_code == 404)

missing = TestClient(create_app(dist_dir=TMP / "does-not-exist"))
r = missing.get("/")
check("missing build reports a build instruction", r.status_code == 503 and "build" in r.text.lower())

print()
print("Passed: " + str(len(passed)) + "  Failed: " + str(len(failed)))
import shutil  # noqa: E402

shutil.rmtree(TMP, ignore_errors=True)
if failed:
    sys.exit(1)
