"""
Browser terminal for the Collig CLI.

The browser surface is an xterm.js emulator connected over a WebSocket to a
real PTY.  That is the easy half.  The hard half is that core/cli.py has a
!<command> escape hatch, so a naively spawned PTY would give every visitor a
shell on the server:

    !ls /home

The only trustworthy boundary against that is an OS/container boundary -- not a
command deny-list.  A deny-list is bypassed by !/bin/ls, !python -c or !cat
before the first review.  This module therefore runs the CLI inside a
short-lived Docker container with:

* only the session's own $HOME and /workspace mounted;
* a read-only root filesystem, no Linux capabilities, no-new-privileges,
  PID/CPU/memory limits and a private network namespace;
* a per-session internal Docker network.  The container has no route to the
  host/LAN/Internet; only a tiny relay sidecar is reachable;
* no provider credentials.  The CLI talks to a per-session LLM proxy on the
  host through the relay.  The proxy injects the real key.  A user who runs
  !env or !cat ~/.collig/config.json finds only a disposable token that can
  call one endpoint on one session.

Configuration (environment):

COLLIG_TERMINAL_ENABLED          default 1
COLLIG_TERMINAL_TOKEN            shared access token.  If unset, a random one
                                 is generated at ~/.collig/terminal.token.
COLLIG_TERMINAL_ALLOW_LOCAL      default 1.  Loopback clients may fetch the
                                 token from the bootstrap endpoint so localhost
                                 development is frictionless.  Remote clients
                                 always need the token.
COLLIG_TERMINAL_BACKEND          docker (default) or host-unsafe
COLLIG_TERMINAL_IMAGE            default collig-terminal:latest
COLLIG_TERMINAL_NETWORK          internal (default), bridge or none.  bridge
                                 lets the sandbox reach the Internet and the
                                 host, so it is opt-in only.
COLLIG_TERMINAL_PROXY_PORT       host port the relay calls, default: the port
                                 the browser request arrived on.
COLLIG_TERMINAL_ROOT             session data root, default ~/.collig/terminal.
COLLIG_TERMINAL_MAX_SESSIONS     default 8
COLLIG_TERMINAL_IDLE_TIMEOUT     default 900 seconds
COLLIG_TERMINAL_MAX_DURATION     default 3600 seconds
"""

from __future__ import annotations

import fcntl
import hmac
import ipaddress
import json
import os
import pty
import secrets
import shutil
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, Optional
from urllib.parse import urlparse

DEFAULT_IMAGE = "collig-terminal:latest"


class TerminalError(RuntimeError):
    """A terminal session cannot be created or started."""


class TerminalUnavailable(TerminalError):
    """The configured backend is not ready (for example, image not built)."""


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or "").strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() not in {"0", "false", "no", "off", "disabled"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name) or default)
    except (TypeError, ValueError):
        return default


def _collig_home() -> Path:
    """Resolve the same home core.paths uses, without importing it eagerly."""
    raw = _env("COLLIG_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(os.path.expanduser("~/.collig")).resolve()


@dataclass
class TerminalSettings:
    enabled: bool = True
    token: str = ""
    token_file: Path = field(default_factory=lambda: _collig_home() / "terminal.token")
    allow_local_bootstrap: bool = True
    backend: str = "docker"
    image: str = DEFAULT_IMAGE
    network: str = "internal"
    root: Path = field(default_factory=lambda: _collig_home() / "terminal")
    proxy_port: int = 0
    max_sessions: int = 8
    idle_timeout: int = 900
    max_duration: int = 3600
    ticket_ttl: int = 60
    keep_sessions: bool = False
    memory: str = "1g"
    cpus: str = "1.0"
    relay_host: str = "host.docker.internal"
    relay_port: int = 8080
    proxy_rate_limit: int = 240
    proxy_rate_window: int = 600

    @classmethod
    def from_env(cls) -> "TerminalSettings":
        home = _collig_home()
        network = _env("COLLIG_TERMINAL_NETWORK", "internal").lower()
        if network not in {"internal", "bridge", "none"}:
            network = "internal"
        backend = _env("COLLIG_TERMINAL_BACKEND", "docker").lower()
        if backend not in {"docker", "host-unsafe"}:
            backend = "docker"
        return cls(
            enabled=_env_bool("COLLIG_TERMINAL_ENABLED", True),
            token=_env("COLLIG_TERMINAL_TOKEN"),
            token_file=Path(_env("COLLIG_TERMINAL_TOKEN_FILE", str(home / "terminal.token"))).expanduser(),
            allow_local_bootstrap=_env_bool("COLLIG_TERMINAL_ALLOW_LOCAL", True),
            backend=backend,
            image=_env("COLLIG_TERMINAL_IMAGE", DEFAULT_IMAGE),
            network=network,
            root=Path(_env("COLLIG_TERMINAL_ROOT", str(home / "terminal"))).expanduser(),
            proxy_port=_env_int("COLLIG_TERMINAL_PROXY_PORT", 0),
            max_sessions=max(1, _env_int("COLLIG_TERMINAL_MAX_SESSIONS", 8)),
            idle_timeout=max(30, _env_int("COLLIG_TERMINAL_IDLE_TIMEOUT", 900)),
            max_duration=max(60, _env_int("COLLIG_TERMINAL_MAX_DURATION", 3600)),
            ticket_ttl=max(10, _env_int("COLLIG_TERMINAL_TICKET_TTL", 60)),
            keep_sessions=_env_bool("COLLIG_TERMINAL_KEEP_SESSIONS", False),
            memory=_env("COLLIG_TERMINAL_MEMORY", "1g"),
            cpus=_env("COLLIG_TERMINAL_CPUS", "1.0"),
            relay_host=_env("COLLIG_TERMINAL_RELAY_HOST", "host.docker.internal"),
            relay_port=max(1, _env_int("COLLIG_TERMINAL_RELAY_PORT", 8080)),
            proxy_rate_limit=max(1, _env_int("COLLIG_TERMINAL_PROXY_RATE_LIMIT", 240)),
            proxy_rate_window=max(10, _env_int("COLLIG_TERMINAL_PROXY_RATE_WINDOW", 600)),
        )


@dataclass
class TerminalSession:
    id: str
    root: Path
    home: Path
    workspace: Path
    proxy_token: str
    created_at: float
    last_activity: float
    proxy_port: int = 0
    ticket: Optional[str] = None
    ticket_expires: float = 0.0
    ws_connected: bool = False
    status: str = "created"
    process: Optional["TerminalProcess"] = None
    network_name: str = ""
    relay_name: str = ""
    container_name: str = ""
    requests: Deque[float] = field(default_factory=deque)

    def touch(self) -> None:
        self.last_activity = time.time()


class TerminalProcess:
    """A child process attached to a PTY.

    Docker's run -it sees the slave side as a real terminal, so the Collig CLI
    (prompt_toolkit/Rich) behaves exactly as it does locally.  The browser
    talks to the master side over the WebSocket.
    """

    def __init__(
        self,
        command,
        *,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        cols: int = 120,
        rows: int = 32,
    ):
        self.command = list(command)
        self.master_fd, slave_fd = pty.openpty()
        self._closed = False
        try:
            _set_winsize(self.master_fd, rows=rows, cols=cols)
            self.proc = subprocess.Popen(
                self.command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=env,
                cwd=cwd,
                close_fds=True,
                start_new_session=True,
            )
        except Exception:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            raise
        finally:
            try:
                os.close(slave_fd)
            except OSError:
                pass

    @property
    def pid(self) -> int:
        return int(self.proc.pid)

    def poll(self) -> Optional[int]:
        return self.proc.poll()

    def read(self, size: int = 65536) -> bytes:
        return os.read(self.master_fd, size)

    def write(self, data: bytes) -> None:
        if not data or self._closed:
            return
        os.write(self.master_fd, data)

    def resize(self, cols: int, rows: int) -> None:
        cols = max(20, min(int(cols), 500))
        rows = max(5, min(int(rows), 200))
        try:
            _set_winsize(self.master_fd, rows=rows, cols=cols)
            os.killpg(os.getpgid(self.proc.pid), signal.SIGWINCH)
        except (OSError, ProcessLookupError):
            pass

    def terminate(self, timeout: float = 3.0) -> None:
        if self._closed:
            return
        self._closed = True
        if self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                try:
                    self.proc.terminate()
                except OSError:
                    pass
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    try:
                        self.proc.kill()
                    except OSError:
                        pass
        try:
            os.close(self.master_fd)
        except OSError:
            pass


def _set_winsize(fd: int, *, rows: int, cols: int) -> None:
    packed = struct.pack("HHHH", int(rows), int(cols), 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, packed)


def _is_loopback(value: Optional[str]) -> bool:
    if not value:
        return False
    host = value.strip().lower()
    if host in {"localhost", "localhost.localdomain"}:
        return True
    if host.startswith("::ffff:"):
        host = host[7:]
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _origin_matches(origin: str, host_header: str) -> bool:
    """Same-origin check that also tolerates an https reverse proxy."""
    try:
        parsed = urlparse(origin)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = (host_header or "").strip().lower()
    netloc = parsed.netloc.lower()
    if netloc == host:
        return True
    # A proxy may terminate TLS: origin is https://example.com while Host is
    # example.com (no port).  Accept the same hostname with either default port.
    origin_host = parsed.hostname or ""
    host_only = host.split(":", 1)[0]
    if origin_host and origin_host == host_only:
        if parsed.port in (None, 80, 443) and (":" not in host or host.endswith((":80", ":443"))):
            return True
    return False


class TerminalManager:
    """Owns terminal sessions, access control and the Docker sandbox."""

    def __init__(self, settings: Optional[TerminalSettings] = None):
        self.settings = settings or TerminalSettings.from_env()
        self._lock = threading.RLock()
        self._sessions: Dict[str, TerminalSession] = {}
        self._token: Optional[str] = self.settings.token or None
        self._docker_checked_at = 0.0
        self._docker_ok: Optional[bool] = None
        self._docker_error = ""

    # ------------------------------------------------------------------
    # access control
    # ------------------------------------------------------------------
    @property
    def token(self) -> str:
        with self._lock:
            if self._token:
                return self._token
            path = Path(self.settings.token_file).expanduser()
            try:
                if path.exists():
                    value = path.read_text(encoding="utf-8").strip()
                    if value:
                        self._token = value
                        return value
            except OSError:
                pass
            value = secrets.token_urlsafe(32)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value + "\n", encoding="utf-8")
                os.chmod(path, 0o600)
            except OSError:
                # Keep the generated token for this process even if the file
                # cannot be written; the local bootstrap endpoint still works.
                pass
            self._token = value
            return value

    def authorize(self, supplied: Optional[str]) -> bool:
        if not self.settings.enabled:
            return False
        if not supplied:
            return False
        expected = self.token
        return bool(expected) and hmac.compare_digest(str(supplied), expected)

    def bootstrap_allowed(self, client_host: Optional[str], headers: Dict[str, str]) -> bool:
        """Return the token to same-machine browsers only.

        request.client.host is the TCP peer.  If any forwarding header is
        present we refuse: behind a reverse proxy every request looks like
        loopback, so auto-revealing the token there would be an auth bypass.
        Shared deployments must set COLLIG_TERMINAL_TOKEN and type it.
        """
        if not self.settings.allow_local_bootstrap:
            return False
        lowered = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        if any(lowered.get(h) for h in ("x-forwarded-for", "x-real-ip", "forwarded", "cf-connecting-ip")):
            return False
        return _is_loopback(client_host)

    def origin_allowed(self, origin: Optional[str], host_header: Optional[str]) -> bool:
        """Reject cross-site WebSocket/HTTP requests.

        A valid token is still required; this is the CSRF / "evil page opens a
        WebSocket to localhost" defence.  Non-browser clients that omit Origin
        are rejected on purpose.
        """
        if not origin:
            return False
        if _origin_matches(origin, host_header or ""):
            return True
        extra = [p.strip() for p in _env("COLLIG_TERMINAL_ALLOWED_ORIGINS").split(",") if p.strip()]
        return origin.rstrip("/") in {item.rstrip("/") for item in extra}

    # ------------------------------------------------------------------
    # readiness / status
    # ------------------------------------------------------------------
    def _docker(self) -> Optional[str]:
        return shutil.which("docker")

    def readiness(self) -> tuple[bool, str]:
        if not self.settings.enabled:
            return False, "terminal is disabled (COLLIG_TERMINAL_ENABLED=0)"
        if self.settings.backend == "host-unsafe":
            if not _env_bool("COLLIG_TERMINAL_ALLOW_UNSANDBOXED", False):
                return False, (
                    "COLLIG_TERMINAL_BACKEND=host-unsafe requires "
                    "COLLIG_TERMINAL_ALLOW_UNSANDBOXED=1; use Docker instead"
                )
            return True, ""
        docker = self._docker()
        if not docker:
            return False, "Docker is not installed or not on PATH"
        now = time.time()
        if self._docker_ok is None or now - self._docker_checked_at > 10:
            self._docker_checked_at = now
            self._docker_ok = False
            self._docker_error = ""
            try:
                info = subprocess.run(
                    [docker, "info", "--format", "{{.ServerVersion}}"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if info.returncode != 0:
                    self._docker_error = (info.stderr or info.stdout or "docker info failed").strip()
                else:
                    image = subprocess.run(
                        [docker, "image", "inspect", self.settings.image],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if image.returncode != 0:
                        self._docker_error = (
                            "Docker image " + repr(self.settings.image) + " is missing; run make terminal-image"
                        )
                    else:
                        self._docker_ok = True
            except Exception as exc:  # pragma: no cover - environment dependent
                self._docker_error = str(exc)
        return bool(self._docker_ok), self._docker_error

    def status(self) -> Dict[str, Any]:
        self.reap_expired()
        ready, reason = self.readiness()
        active = [s for s in self._sessions.values() if s.status in {"starting", "running", "connected"}]
        return {
            "enabled": self.settings.enabled,
            "ready": ready,
            "reason": reason,
            "backend": self.settings.backend,
            "image": self.settings.image,
            "network": self.settings.network,
            "active_sessions": len(active),
            "max_sessions": self.settings.max_sessions,
            "idle_timeout": self.settings.idle_timeout,
            "max_duration": self.settings.max_duration,
            "local_bootstrap": self.settings.allow_local_bootstrap,
        }

    # ------------------------------------------------------------------
    # session lifecycle
    # ------------------------------------------------------------------
    def create_session(self, proxy_port: int = 0) -> Dict[str, Any]:
        ready, reason = self.readiness()
        if not ready:
            raise TerminalUnavailable(reason)
        self.reap_expired()
        with self._lock:
            active = [s for s in self._sessions.values() if s.status != "closed"]
            if len(active) >= self.settings.max_sessions:
                raise TerminalError("too many active terminal sessions (" + str(len(active)) + ")")
            sid = secrets.token_hex(8)
            root = (self.settings.root / "sessions" / sid).resolve()
            home = root / "home"
            workspace = root / "workspace"
            for path in (home, workspace):
                path.mkdir(parents=True, exist_ok=True)
                try:
                    os.chmod(path, 0o700)
                except OSError:
                    pass
            session = TerminalSession(
                id=sid,
                root=root,
                home=home,
                workspace=workspace,
                proxy_token=secrets.token_urlsafe(32),
                created_at=time.time(),
                last_activity=time.time(),
                proxy_port=int(proxy_port or self.settings.proxy_port or 0),
                network_name=f"collig-term-{sid}",
                relay_name=f"collig-relay-{sid}",
                container_name=f"collig-term-{sid}",
            )
            self._write_session_config(session)
            self._sessions[sid] = session
            ticket = self.issue_ticket(sid)
        return {
            "session_id": sid,
            "ticket": ticket["ticket"],
            "expires_in": ticket["expires_in"],
            "ws_path": "/api/terminal/ws?ticket=" + ticket["ticket"],
        }

    def issue_ticket(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.status == "closed":
                raise TerminalError("terminal session not found")
            if session.ws_connected:
                raise TerminalError("terminal session is already connected")
            session.ticket = secrets.token_urlsafe(32)
            session.ticket_expires = time.time() + self.settings.ticket_ttl
            return {"ticket": session.ticket, "expires_in": self.settings.ticket_ttl}

    def consume_ticket(self, ticket: Optional[str]) -> Optional[TerminalSession]:
        if not ticket:
            return None
        now = time.time()
        with self._lock:
            for session in self._sessions.values():
                if not session.ticket:
                    continue
                if now > session.ticket_expires:
                    session.ticket = None
                    continue
                if hmac.compare_digest(str(ticket), session.ticket):
                    session.ticket = None
                    return session
        return None

    def get_session(self, session_id: str) -> Optional[TerminalSession]:
        with self._lock:
            return self._sessions.get(session_id)

    def find_by_proxy_token(self, token: Optional[str]) -> Optional[TerminalSession]:
        if not token:
            return None
        with self._lock:
            for session in self._sessions.values():
                if session.status != "closed" and hmac.compare_digest(str(token), session.proxy_token):
                    return session
        return None

    def mark_connected(self, session: TerminalSession) -> bool:
        with self._lock:
            if session.status == "closed" or session.ws_connected:
                return False
            session.ws_connected = True
            session.status = "starting"
            session.touch()
            return True

    def release(self, session: TerminalSession) -> None:
        self.cleanup(session)

    def cleanup(self, session: Optional[TerminalSession]) -> None:
        if session is None:
            return
        with self._lock:
            if self._sessions.get(session.id) is session:
                self._sessions.pop(session.id, None)
            session.status = "closed"
            session.ws_connected = False
        proc = session.process
        session.process = None
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        docker = self._docker()
        if docker:
            for name in (session.container_name, session.relay_name):
                if name:
                    try:
                        subprocess.run(
                            [docker, "rm", "-f", name],
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )
                    except Exception:
                        pass
            if session.network_name:
                try:
                    subprocess.run(
                        [docker, "network", "rm", session.network_name],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                except Exception:
                    pass
        if not self.settings.keep_sessions:
            try:
                shutil.rmtree(session.root)
            except OSError:
                pass
        else:
            try:
                (session.root / "closed.json").write_text(
                    json.dumps({"closed_at": time.time(), "status": "closed"}, indent=2),
                    encoding="utf-8",
                )
            except OSError:
                pass

    def reap_expired(self) -> int:
        now = time.time()
        doomed = []
        with self._lock:
            for session in list(self._sessions.values()):
                if session.status == "closed":
                    doomed.append(session)
                    continue
                age = now - session.created_at
                idle = now - session.last_activity
                if age > self.settings.max_duration or idle > self.settings.idle_timeout:
                    doomed.append(session)
                elif session.status == "created" and age > 300:
                    doomed.append(session)
        for session in doomed:
            self.cleanup(session)
        return len(doomed)

    def allow_proxy_request(self, session: TerminalSession) -> bool:
        now = time.time()
        with self._lock:
            window = self.settings.proxy_rate_window
            while session.requests and now - session.requests[0] > window:
                session.requests.popleft()
            if len(session.requests) >= self.settings.proxy_rate_limit:
                return False
            session.requests.append(now)
            session.touch()
            return True

    # ------------------------------------------------------------------
    # sandbox commands
    # ------------------------------------------------------------------
    def _write_session_config(self, session: TerminalSession) -> None:
        try:
            from core.runtime import get_llm_config, load_config
        except Exception:
            load_config = None  # type: ignore
            get_llm_config = None  # type: ignore
        model = ""
        if load_config is not None and get_llm_config is not None:
            try:
                model = str(get_llm_config(load_config()).get("llm_model") or "")
            except Exception:
                model = ""
        # The Docker backend must never put the per-session proxy token in
        # config.json: "!cat ~/.collig/config.json" and "/config list" are
        # available to the terminal user.  The relay sidecar holds the token
        # and forwards a fixed /v1 prefix; the CLI only needs an arbitrary
        # OpenAI-compatible key value.
        host_unsafe = self.settings.backend == "host-unsafe"
        if session.proxy_port and host_unsafe:
            base_url = (
                "http://127.0.0.1:" + str(session.proxy_port) + "/api/terminal/llm/" + session.proxy_token + "/v1"
            )
        else:
            base_url = "http://relay:" + str(self.settings.relay_port) + "/v1"
        config = {
            "LLM_PROVIDER": "custom",
            "provider": "custom",
            "CUSTOM_BASE_URL": base_url,
            "CUSTOM_API_KEY": session.proxy_token if host_unsafe else "relay-managed",
            "LLM_MODEL": model,
            "ENABLE_MARKDOWN": True,
            "USER_MEMORY_ENABLED": False,
            "USER_MEMORY_LLM_EXTRACT": False,
            "COLLIG_WEB_TERMINAL": True,
        }
        config_dir = session.home / ".collig"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.json"
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        try:
            os.chmod(config_path, 0o600)
        except OSError:
            pass

    def _uid_gid(self) -> tuple[int, int]:
        try:
            uid = os.getuid()
            gid = os.getgid()
        except AttributeError:  # pragma: no cover - Windows
            return 10001, 10001
        if uid == 0:
            return 10001, 10001
        return uid, gid

    def _docker_base(self) -> list[str]:
        docker = self._docker()
        if not docker:
            raise TerminalUnavailable("Docker is not installed or not on PATH")
        return [docker]

    def build_relay_command(self, session: TerminalSession) -> list[str]:
        target = (
            "http://"
            + self.settings.relay_host
            + ":"
            + str(session.proxy_port)
            + "/api/terminal/llm/"
            + session.proxy_token
        )
        uid, gid = self._uid_gid()
        cmd = self._docker_base() + [
            "run",
            "-d",
            "--rm",
            "--name",
            session.relay_name,
            "--label",
            "collig.terminal.session=" + session.id,
            "--network",
            "bridge",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=32m",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            "64",
            "--memory",
            "256m",
            "--cpus",
            "0.5",
            "--user",
            f"{uid}:{gid}",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-e",
            "PYTHONUNBUFFERED=1",
            "-e",
            "COLLIG_TERMINAL_RELAY_PORT=" + str(self.settings.relay_port),
            "-e",
            "COLLIG_TERMINAL_RELAY_TARGET=" + target,
        ]
        if sys.platform.startswith("linux"):
            cmd += ["--add-host", "host.docker.internal:host-gateway"]
        cmd += [self.settings.image, "python", "/app/terminal/relay.py"]
        return cmd

    def build_terminal_command(self, session: TerminalSession) -> list[str]:
        uid, gid = self._uid_gid()
        network = session.network_name if self.settings.network != "none" else "none"
        cmd = self._docker_base() + [
            "run",
            "--rm",
            "-it",
            "--name",
            session.container_name,
            "--label",
            "collig.terminal.session=" + session.id,
            "--network",
            network,
            "--hostname",
            "collig",
            "--init",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            "256",
            "--memory",
            self.settings.memory,
            "--cpus",
            self.settings.cpus,
            "--ulimit",
            "nofile=1024:1024",
            "--user",
            f"{uid}:{gid}",
            "--mount",
            "type=bind,source=" + str(session.home.resolve()) + ",target=/home/collig",
            "--mount",
            "type=bind,source=" + str(session.workspace.resolve()) + ",target=/workspace",
            "--workdir",
            "/workspace",
            "-e",
            "HOME=/home/collig",
            "-e",
            "COLLIG_HOME=/home/collig/.collig",
            "-e",
            "TERM=xterm-256color",
            "-e",
            "LANG=C.UTF-8",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-e",
            "PYTHONUNBUFFERED=1",
            "-e",
            "LITELLM_LOCAL_MODEL_COST_MAP=True",
            "-e",
            "COLLIG_WEB_TERMINAL=1",
            "-e",
            "COLLIG_TERMINAL_SESSION=" + session.id,
            self.settings.image,
            "python",
            "/app/core/cli.py",
        ]
        return cmd

    def spawn(self, session: TerminalSession, cols: int = 120, rows: int = 32) -> TerminalProcess:
        if session.process is not None:
            return session.process
        if self.settings.backend == "host-unsafe":
            if not _env_bool("COLLIG_TERMINAL_ALLOW_UNSANDBOXED", False):
                raise TerminalUnavailable("host-unsafe backend is not explicitly enabled")
            command = [sys.executable, str(Path(__file__).resolve().parent / "cli.py")]
            env = self._host_env(session)
            cwd = str(session.workspace)
        else:
            ready, reason = self.readiness()
            if not ready:
                raise TerminalUnavailable(reason)
            if self.settings.network != "none":
                self._start_relay(session)
            command = self.build_terminal_command(session)
            env = os.environ.copy()
            cwd = str(session.workspace)
        try:
            proc = TerminalProcess(command, env=env, cwd=cwd, cols=cols, rows=rows)
        except Exception:
            self.cleanup(session)
            raise
        session.process = proc
        session.status = "running"
        session.touch()
        return proc

    def _host_env(self, session: TerminalSession) -> Dict[str, str]:
        allowed = ("PATH", "LANG", "LC_ALL", "TMPDIR", "TERM")
        env = {key: os.environ[key] for key in allowed if os.environ.get(key)}
        env.update(
            {
                "HOME": str(session.home),
                "COLLIG_HOME": str(session.home / ".collig"),
                "TERM": "xterm-256color",
                "COLLIG_WEB_TERMINAL": "1",
                "COLLIG_TERMINAL_SESSION": session.id,
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
            }
        )
        return env

    def _start_relay(self, session: TerminalSession) -> None:
        network = session.network_name
        docker = self._docker_base()
        try:
            subprocess.run(
                [*docker, "network", "rm", network],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            pass
        create_cmd = [*docker, "network", "create"]
        if self.settings.network == "internal":
            create_cmd.append("--internal")
        create_cmd.append(network)
        created = subprocess.run(create_cmd, capture_output=True, text=True, timeout=20)
        if created.returncode != 0:
            raise TerminalError("could not create terminal network: " + created.stderr.strip())
        relay = subprocess.run(
            self.build_relay_command(session),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if relay.returncode != 0:
            try:
                subprocess.run([*docker, "network", "rm", network], capture_output=True, timeout=10)
            except Exception:
                pass
            raise TerminalError("could not start terminal relay: " + relay.stderr.strip())
        # Wait until the relay is actually running.  A container that exits
        # during startup is "marked for removal", and network connect would
        # then fail with a confusing daemon error.
        running = False
        for _ in range(30):
            probe = subprocess.run(
                [*docker, "inspect", "-f", "{{.State.Running}}", session.relay_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if probe.returncode == 0 and probe.stdout.strip() == "true":
                running = True
                break
            if probe.returncode == 0 and probe.stdout.strip() == "false":
                break
            time.sleep(0.1)
        if not running:
            logs = subprocess.run(
                [*docker, "logs", session.relay_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            detail = (logs.stderr or logs.stdout or "").strip()
            self.cleanup(session)
            raise TerminalError("terminal relay exited during startup: " + detail)

        # Attach the relay to the private network too.  The alias is what the
        # CLI uses; the container name itself is deliberately not advertised.
        attached = subprocess.run(
            [
                *docker,
                "network",
                "connect",
                "--alias",
                "relay",
                network,
                session.relay_name,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if attached.returncode != 0:
            self.cleanup(session)
            raise TerminalError("could not attach terminal relay: " + attached.stderr.strip())
        # Give the relay a moment to bind.  The CLI does not call the model
        # until the first prompt, so this is only to avoid a race on start.
        time.sleep(0.2)


_MANAGER: Optional[TerminalManager] = None
_MANAGER_LOCK = threading.Lock()


def get_terminal_manager() -> TerminalManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = TerminalManager()
        return _MANAGER


def reset_terminal_manager(settings: Optional[TerminalSettings] = None) -> TerminalManager:
    """Testing helper: replace the process-wide manager."""
    global _MANAGER
    with _MANAGER_LOCK:
        _MANAGER = TerminalManager(settings)
        return _MANAGER
