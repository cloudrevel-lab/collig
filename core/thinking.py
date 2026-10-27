"""
Intuitive thinking / planning display for agent turns.

The old CLI printed a flat "[Thinking Process]" heading and a couple of
indented lines.  This module renders a live, structured timeline instead:

    ◆ Thinking · 2.4s
      ✔ Understanding   what's the weather in Sydney?
      ✔ Skills          Weather Reporter · 1 tool
      ✔ Plan            get_weather(city="Sydney")
      ✔ Tool            get_weather  0.41s
      ✔ Answer          It is 22°C and sunny in Sydney.

The block is a Rich Live region while the model is planning; it is stopped
before answer tokens stream so the two do not fight for the terminal.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, List, Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text


@dataclass
class Step:
    kind: str
    label: str
    detail: str = ""
    status: str = "done"
    started: float = field(default_factory=time.monotonic)
    elapsed: Optional[float] = None


_ICONS = {
    "done": "✔",
    "running": "◐",
    "info": "•",
    "tool": "⚙",
    "error": "✖",
}


def _short(value: Any, limit: int = 180) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


class ThinkingBlock:
    """Structured, live thinking timeline for one turn."""

    def __init__(self, console: Console, enabled: bool = True):
        self.console = console
        self.enabled = bool(enabled)
        self.interactive = bool(getattr(console, "is_terminal", False))
        self.steps: List[Step] = []
        self.started = time.monotonic()
        self.live: Optional[Live] = None
        self._finished = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def begin(self, message: str = "") -> None:
        if not self.enabled:
            return
        self.started = time.monotonic()
        self.steps = [Step("understanding", "Understanding", _short(message, 120))]
        if self.interactive:
            self.live = Live(
                self._render(),
                console=self.console,
                refresh_per_second=8,
                transient=False,
            )
            self.live.start()

    def _elapsed(self) -> float:
        return time.monotonic() - self.started

    def _add(self, kind: str, label: str, detail: str = "", status: str = "done") -> Step:
        step = Step(kind=kind, label=label, detail=detail, status=status)
        if kind == "thought" and self.steps and self.steps[-1].kind == "thought":
            previous = self.steps[-1]
            previous.detail = _short((previous.detail + " " + detail).strip(), 400)
        else:
            self.steps.append(step)
        self._refresh()
        return step

    def _refresh(self) -> None:
        if self.live is not None:
            self.live.update(self._render())

    def _render(self) -> Panel:
        body = Text()
        body.append("◆ Thinking", style="bold cyan")
        body.append(f"  {self._elapsed():.1f}s", style="dim")
        body.append("\n")
        if not self.steps:
            body.append("  waiting for the model…", style="dim italic")
        for step in self.steps:
            icon = _ICONS.get(step.status, "•")
            if step.kind == "tool":
                icon = _ICONS["tool"] if step.status != "error" else _ICONS["error"]
            elif step.status == "running":
                icon = _ICONS["running"]
            elif step.status == "error":
                icon = _ICONS["error"]
            style = {
                "done": "green",
                "running": "yellow",
                "error": "red",
                "info": "dim",
            }.get(step.status, "white")
            body.append("  ")
            body.append(icon + " ", style=style)
            body.append(step.label, style="bold")
            if step.detail:
                body.append("  " + step.detail, style="dim")
            if step.elapsed is not None:
                body.append(f"  ({step.elapsed:.2f}s)", style="dim")
            body.append("\n")
        return Panel(
            body,
            border_style="cyan" if self.live is not None else "dim",
            padding=(0, 1),
        )

    def finish(self) -> None:
        if not self.enabled or self._finished:
            return
        self._finished = True
        for step in self.steps:
            if step.status == "running":
                step.status = "done"
                step.elapsed = time.monotonic() - step.started
        if self.live is not None:
            self.live.update(self._render())
            self.live.stop()
            self.live = None
        elif self.steps and self.interactive:
            self.console.print(self._render())
            self.console.print()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def route(self, route: Any) -> None:
        if not self.enabled:
            return
        try:
            summary = route.summary()
        except Exception:
            summary = str(route)
        self._add("skills", "Skills", summary)

    def thought(self, text: str) -> None:
        if self.enabled and text and text.strip():
            self._add("thought", "Thinking", _short(text, 400))

    def plan(self, name: str, args: Any = None) -> None:
        if not self.enabled:
            return
        detail = ""
        if args:
            try:
                import json

                detail = json.dumps(args, default=str, ensure_ascii=False)
            except Exception:
                detail = str(args)
        self._add("plan", "Plan", f"{name}({_short(detail, 120)})", status="running")

    def tool_start(self, name: str) -> None:
        if self.enabled:
            self._add("tool", "Tool", name, status="running")

    def tool_end(self, name: str, ok: bool = True, detail: str = "") -> None:
        if not self.enabled:
            return
        for step in reversed(self.steps):
            if step.kind == "tool" and step.detail == name and step.status == "running":
                step.status = "done" if ok else "error"
                step.elapsed = time.monotonic() - step.started
                if detail:
                    step.detail = f"{name}  {_short(detail, 140)}"
                self._refresh()
                return
        self._add("tool", "Tool", f"{name}  {_short(detail, 140)}", status="done" if ok else "error")

    def transfer(self, agent_name: str) -> None:
        if self.enabled:
            self._add("transfer", "Delegating", agent_name)

    def answering(self) -> None:
        if self.enabled and not any(s.kind == "answer" for s in self.steps):
            self._add("answer", "Responding", "", status="running")

    def error(self, message: str) -> None:
        if self.enabled:
            self._add("error", "Error", _short(message, 200), status="error")
