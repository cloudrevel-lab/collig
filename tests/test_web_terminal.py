#!/usr/bin/env python3
"""Offline tests for the web terminal's security boundary and session plumbing."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
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


from core.terminal import (  # noqa: E402
    TerminalManager,
    TerminalSettings,
    _origin_matches,
)

TMP = Path(tempfile.mkdtemp(prefix="collig-terminal-test-"))
os.environ["COLLIG_TERMINAL_ALLOW_UNSANDBOXED"] = "1"

settings = TerminalSettings(
    enabled=True,
    token="test-token-abcdefghijklmnopqrstuvwxyz",
    token_file=TMP / "terminal.token",
    allow_local_bootstrap=True,
    backend="docker",
    root=TMP / "sessions-root",
    proxy_port=5555,
    max_sessions=2,
    ticket_ttl=30,
)
mgr = TerminalManager(settings)
mgr._docker = lambda: None  # never touch a real Docker daemon in this test
mgr.readiness = lambda: (True, "")  # command builders are tested below

# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------
check("token is accepted", mgr.authorize(settings.token))
check("wrong token is rejected", not mgr.authorize("wrong"))
check("empty token is rejected", not mgr.authorize(""))
check("loopback browser gets bootstrap token", mgr.bootstrap_allowed("127.0.0.1", {}))
check("IPv6 loopback gets bootstrap token", mgr.bootstrap_allowed("::1", {}))
check("remote client does not get bootstrap token", not mgr.bootstrap_allowed("10.0.0.7", {}))
check(
    "forwarded request is never treated as local",
    not mgr.bootstrap_allowed("127.0.0.1", {"x-forwarded-for": "203.0.113.9"}),
)
check(
    "same-origin websocket is allowed",
    mgr.origin_allowed("http://127.0.0.1:5005", "127.0.0.1:5005"),
)
check(
    "foreign-origin websocket is rejected",
    not mgr.origin_allowed("https://evil.example", "127.0.0.1:5005"),
)
check("missing origin is rejected", not mgr.origin_allowed(None, "127.0.0.1:5005"))
check(
    "TLS proxy origin with matching host is allowed",
    _origin_matches("https://collig.example.com", "collig.example.com"),
)

# ---------------------------------------------------------------------------
# Session + token lifecycle
# ---------------------------------------------------------------------------
created = mgr.create_session(proxy_port=5555)
sid = created["session_id"]
session = mgr.get_session(sid)
check("session id is generated", bool(sid))
check("session has a short-lived ticket", bool(created["ticket"]))
check("session home is inside the configured root", settings.root.resolve() in session.home.parents)
check("workspace is separate from home", session.home != session.workspace)
check("workspace directory exists", session.workspace.is_dir())
check("session config is written", (session.home / ".collig" / "config.json").is_file())

config = json.loads((session.home / ".collig" / "config.json").read_text())
check("sandbox config selects the proxy provider", config.get("provider") == "custom")
check("sandbox config contains no provider key", "api_key" not in config)
check("sandbox config has only the relay placeholder key", config.get("CUSTOM_API_KEY") == "relay-managed")
check("proxy token is absent from sandbox config", session.proxy_token not in json.dumps(config))
check("per-session token is not the shared access token", session.proxy_token != settings.token)
check("sandbox base URL has no token", config.get("CUSTOM_BASE_URL") == "http://relay:8080/v1")
check("config contains no obvious secret", "sk-" not in json.dumps(config))
check("model is copied, not the API key", isinstance(config.get("LLM_MODEL"), str))

# Tickets are one-shot and expire.
check("ticket can be consumed once", mgr.consume_ticket(created["ticket"]) is session)
check("consumed ticket is rejected", mgr.consume_ticket(created["ticket"]) is None)
second = mgr.issue_ticket(sid)
session.ticket_expires = time.time() - 1
check("expired ticket is rejected", mgr.consume_ticket(second["ticket"]) is None)

# One live WebSocket per session.
ticket3 = mgr.issue_ticket(sid)["ticket"]
check("session accepts its first websocket", mgr.mark_connected(session))
check("second websocket for the same session is rejected", not mgr.mark_connected(session))

# ---------------------------------------------------------------------------
# Docker command is the actual security boundary
# ---------------------------------------------------------------------------
mgr._docker = lambda: "/usr/bin/docker"
terminal_cmd = mgr.build_terminal_command(session)
joined = " ".join(terminal_cmd)
check("terminal is read-only", "--read-only" in terminal_cmd)
check("terminal drops all capabilities", "--cap-drop ALL" in joined)
check("terminal forbids privilege escalation", "no-new-privileges:true" in joined)
check("terminal has PID limit", "--pids-limit" in terminal_cmd)
check("terminal has memory limit", "--memory" in terminal_cmd)
check("terminal uses a private network", session.network_name in terminal_cmd)
check("home mount is the session home", "source=" + str(session.home.resolve()) in joined)
check("workspace mount is the session workspace", "source=" + str(session.workspace.resolve()) in joined)
check("no host repository mount", "/app:ro" not in joined and PROJECT not in joined)
check("only /app/core/cli.py runs", "/app/core/cli.py" in terminal_cmd)
check("container has no host API key env", not any("OPENAI_API_KEY" in part for part in terminal_cmd))
check("container home is per session", "HOME=/home/collig" in terminal_cmd)
check("container uses COLLIG_HOME", "COLLIG_HOME=/home/collig/.collig" in terminal_cmd)

relay_cmd = mgr.build_relay_command(session)
relay_joined = " ".join(relay_cmd)
check("relay forwards only the session proxy", session.proxy_token in relay_joined)
check("relay is hardened", "--cap-drop ALL" in relay_joined and "--read-only" in relay_cmd)
check("relay sidecar has no host mount", "type=bind" not in relay_joined)
check("relay runs the relay entrypoint", "/app/terminal/relay.py" in relay_cmd)

# ---------------------------------------------------------------------------
# Relay path allow-list
# ---------------------------------------------------------------------------
relay_path = Path(PROJECT) / "terminal" / "relay.py"
spec = importlib.util.spec_from_file_location("collig_terminal_relay", relay_path)
relay_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay_module)
check("relay allows chat completions", relay_module.allowed_path("chat/completions"))
check("relay allows models", relay_module.allowed_path("models"))
check("relay rejects traversal", not relay_module.allowed_path("../config"))
check("relay rejects arbitrary host paths", not relay_module.allowed_path("../../api/config"))

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
limited = TerminalManager(
    TerminalSettings(
        enabled=True,
        token="x",
        token_file=TMP / "token2",
        backend="host-unsafe",
        root=TMP / "limited",
        proxy_rate_limit=2,
        proxy_rate_window=60,
    )
)
limited._docker = lambda: None
created2 = limited.create_session(proxy_port=5555)
s2 = limited.get_session(created2["session_id"])
check("first proxy call is allowed", limited.allow_proxy_request(s2))
check("second proxy call is allowed", limited.allow_proxy_request(s2))
check("third proxy call is rate-limited", not limited.allow_proxy_request(s2))

# Cleanup must remove the session directory (ephemeral by default).
limited_root = s2.root
limited.cleanup(s2)
check("cleanup removes the session directory", not limited_root.exists())
mgr.cleanup(session)

# ---------------------------------------------------------------------------
# PTY smoke test (no Docker)
# ---------------------------------------------------------------------------
if sys.platform != "win32":
    import select

    from core.terminal import TerminalProcess

    proc = TerminalProcess([sys.executable, "-c", "print('pty-ok')"], env=dict(os.environ), cols=80, rows=24)
    chunks = []
    deadline = time.time() + 5
    while time.time() < deadline:
        ready, _, _ = select.select([proc.master_fd], [], [], 0.5)
        if not ready:
            if proc.poll() is not None:
                break
            continue
        try:
            data = proc.read()
        except OSError:
            break
        if not data:
            break
        chunks.append(data)
        if b"pty-ok" in b"".join(chunks):
            break
    proc.terminate()
    check("PTY streams command output", b"pty-ok" in b"".join(chunks))

print()
print("Passed: " + str(len(passed)) + "  Failed: " + str(len(failed)))
shutil.rmtree(TMP, ignore_errors=True)
if failed:
    sys.exit(1)
