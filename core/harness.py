"""
Harness primitives shared by the CLI and the ADK agent.

The harness is the thin layer between a raw user message and the model:

* intent routing -- pick the few skills that can actually answer the message;
* deterministic tool shortcuts -- `/get_current_time` runs one function, no
  model round-trip and no tool schema payload;
* a shell escape -- `!pwd` runs a real command;
* the event vocabulary the thinking display renders.

Keeping this separate from both the ADK runner and the Rich CLI means the web
surface, the terminal and future clients all route and render identically.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Intent routing
# ---------------------------------------------------------------------------

TRIVIAL_PATTERNS = [
    # Simple maths: "1+1", "what is 2+2", "calculate 100 / 5"
    re.compile(r"^(what(?:\s*[\']s)?|calc(?:ulate)?|solve)\s*:?\s*\d+\s*[\+\-\*/x÷]\s*\d+", re.IGNORECASE),
    re.compile(r"^\d+\s*[\+\-\*/x÷]\s*\d+"),
    # Greetings
    re.compile(r"^(hi|hello|hey|greetings|good\s+(morning|afternoon|evening|day))\.?$", re.IGNORECASE),
    # Simple identity questions
    re.compile(r"^(who\s+are\s+you|what\s+are\s+you|what\s+(is|are)\s+your\s+(name|capabilities))\??$", re.IGNORECASE),
    # Thanks
    re.compile(r"^(thanks?|thank\s+you|thx|cheers|appreciate\s+it)\.?$", re.IGNORECASE),
]

# Extra intent keywords per skill, keyed by `Skill.name`.  These supplement
# each skill's own triggers rather than replacing them.
SKILL_KEYWORDS: Dict[str, List[str]] = {
    "Weather Reporter": ["weather", "temperature", "forecast", "rain", "sunny", "cold", "hot"],
    "Time": ["time", "clock", "timezone", "what time"],
    "News Search": ["news", "headlines", "latest news", "current events", "breaking news"],
    "Email Manager": ["email", "mail", "inbox", "send email", "check mail", "compose"],
    "File System Manager": [
        "file",
        "directory",
        "folder",
        "read file",
        "write file",
        "create file",
        "list files",
        "delete file",
    ],
    "Git Version Control": ["git", "commit", "push", "pull", "branch", "diff", "stash"],
    "Memory & Notes": ["note", "remember", "save note", "my notes", "search notes"],
    "Bookmarks": ["bookmark", "save link", "saved links", "favorites"],
    "Personal Profile": [
        "my name",
        "my info",
        "personal info",
        "set my name",
        "about me",
        "remember this",
        "save this about",
        "my location",
        "my preference",
    ],
    "System Info": ["system status", "disk space", "memory usage", "install", "package"],
    "Chinese Lunar Calendar": ["lunar", "chinese calendar", "chinese date"],
    "Date Calculator": ["days between", "date calculator", "what date", "add days", "subtract days"],
    "Cache": ["cache", "cached"],
    "Browser": ["open browser", "open website", "launch browser", "browse"],
    "Menu": ["menu", "select from", "choose from"],
    "Survey Automator": ["survey", "questionnaire", "form"],
    "Thinking Toggle": ["hide thinking", "show thinking", "toggle thinking"],
    "Diary": ["diary", "create a diary", "diary entry", "my diary"],
    "Web Search": ["search", "look up", "find information", "google", "search the web", "web search"],
    "jira": [
        "jira",
        "sprint",
        "my plate",
        "on my plate",
        "ticket",
        "tickets",
        "issue",
        "issues",
        "task",
        "tasks",
        "story",
        "stories",
        "backlog",
        "scrum",
        "agile",
        "board",
    ],
}

# Skills that are always safe to expose on an open-ended turn.  Deliberately
# empty: a poem or a chat message needs zero tool schemas, which is the whole
# point of per-turn selection.
DEFAULT_SKILLS: List[str] = []


def is_trivial_query(message: str) -> bool:
    """True when a message plainly needs no tools (greeting, arithmetic, thanks)."""
    msg = (message or "").strip()
    return any(pattern.match(msg) for pattern in TRIVIAL_PATTERNS)


def text_of(context: Optional[Any]) -> str:
    """The text of the user message that started an ADK invocation."""
    if context is None:
        return ""
    content = getattr(context, "user_content", None)
    if content is None or not getattr(content, "parts", None):
        return ""
    return " ".join(part.text for part in content.parts if getattr(part, "text", None))


def keywords_for(skill: Any) -> List[str]:
    """Curated keywords for a skill plus its own SKILL.md triggers."""
    words = list(SKILL_KEYWORDS.get(getattr(skill, "name", ""), []))
    words.extend(str(t).lower() for t in (getattr(skill, "triggers", None) or []))
    seen: Set[str] = set()
    out: List[str] = []
    for word in words:
        word = word.strip().lower()
        if word and word not in seen:
            seen.add(word)
            out.append(word)
    return out


def _keyword_score(message: str, keyword: str) -> int:
    """Weighted match: exact phrase > multi-word phrase > single word."""
    keyword = (keyword or "").strip().lower()
    if not keyword:
        return 0
    if keyword == message:
        return 10
    if keyword not in message:
        return 0
    if " " in keyword:
        return 5
    if re.search(r"\b" + re.escape(keyword) + r"\b", message):
        return 2
    return 0


def _tool_names(skill: Any) -> List[str]:
    try:
        return [str(item.get("name", "")).lower() for item in skill.tool_metadata() if item.get("name")]
    except Exception:
        return []


@dataclass
class Route:
    """The harness's decision for one user message."""

    message: str
    skills: List[Any] = field(default_factory=list)
    scores: Dict[str, int] = field(default_factory=dict)
    trivial: bool = False
    reason: str = ""

    @property
    def names(self) -> List[str]:
        return [getattr(s, "name", "?") for s in self.skills]

    @property
    def tool_metadata(self) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        for skill in self.skills:
            try:
                out.extend(skill.tool_metadata())
            except Exception:
                continue
        return out

    @property
    def tool_count(self) -> int:
        return len(self.tool_metadata)

    def summary(self) -> str:
        if self.trivial:
            return "no tools (trivial query)"
        if not self.skills:
            return "no tools (open-ended request)"
        names = ", ".join(self.names)
        return f"{names} · {self.tool_count} tool{'s' if self.tool_count != 1 else ''}"


def _enabled_skills(manager: Optional[Any] = None) -> List[Any]:
    if manager is None:
        from core.runtime import get_skill_manager

        manager = get_skill_manager()
    return [skill for skill in manager.skills if getattr(skill, "enabled", True)]


def route_message(message: str, manager: Optional[Any] = None, exclude: Optional[Iterable[str]] = None) -> Route:
    """
    Choose the skills relevant to `message`.

    A skill scores on its exact tool names (strongest), its own triggers and
    curated keywords, and its name appearing in the message. Only the clear
    winner(s) survive: if the second score is less than half the top score it
    is dropped. That is why `get_current_time` selects Time but not the
    Date Calculator, whose only overlap is the generic word "time".
    """
    msg = (message or "").strip().lower()
    exclude_set = {str(x).lower() for x in (exclude or ())}
    enabled = [s for s in _enabled_skills(manager) if str(getattr(s, "name", "")).lower() not in exclude_set]

    if not msg or is_trivial_query(msg):
        return Route(message=message, trivial=bool(msg), reason="trivial" if msg else "empty")

    scores: Dict[str, int] = {}
    for skill in enabled:
        name = str(getattr(skill, "name", ""))
        score = 0
        # Exact tool name is the strongest signal: /get_current_time or
        # "get_current_time" should not pull in every date-ish skill.
        for tool_name in _tool_names(skill):
            if tool_name and tool_name in msg:
                score += 10
        if name and name.lower() in msg:
            score += 6
        for keyword in keywords_for(skill):
            score += _keyword_score(msg, keyword)
        if score:
            scores[name] = score

    if not scores:
        return Route(message=message, reason="no match")

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_name, top_score = ranked[0]
    threshold = max(1, top_score // 2)
    winners = {name for name, score in ranked if score >= threshold and score == top_score}
    selected = [s for s in enabled if str(getattr(s, "name", "")) in winners]
    if not selected:
        return Route(message=message, scores=scores, reason="no match")
    return Route(message=message, skills=selected, scores=scores, reason="score")


# ---------------------------------------------------------------------------
# Deterministic tool shortcut
# ---------------------------------------------------------------------------

RESERVED_COMMANDS = {
    "config",
    "provider",
    "news",
    "console",
    "jira",
    "stats",
    "status",
    "doctor",
    "test",
    "backup",
    "restore",
    "load",
    "run",
    "restart",
    "quiet",
    "verbose",
    "toggle",
    "exit",
    "quit",
    "clear",
    "help",
}


def parse_tool_command(text: str) -> Optional[Tuple[str, Any]]:
    """
    Parse `/tool_name [json-or-string]` for the deterministic shortcut.

    Returns `(name, args)` or `None` when the leading token is not a tool we
    know about or is a reserved CLI command.
    """
    if not text or not text.startswith("/"):
        return None
    body = text[1:].strip()
    if not body:
        return None
    parts = body.split(None, 1)
    name = parts[0]
    if name.lower() in RESERVED_COMMANDS:
        return None
    remainder = parts[1].strip() if len(parts) > 1 else ""

    try:
        from core.runtime import get_skill_manager

        manager = get_skill_manager()
    except Exception:
        return None

    for skill in manager.skills:
        if not getattr(skill, "enabled", True):
            continue
        try:
            names = [str(item.get("name", "")) for item in skill.tool_metadata()]
        except Exception:
            names = []
        if name not in names:
            continue
        if not remainder:
            return name, None
        if remainder[0] in '{["':
            try:
                return name, json.loads(remainder)
            except Exception:
                pass
        return name, remainder
    return None


def find_tool(name: str, manager: Optional[Any] = None) -> Optional[Tuple[Any, Any]]:
    """Return `(skill, function)` for a tool name, loading only that skill."""
    if manager is None:
        from core.runtime import get_skill_manager

        manager = get_skill_manager()
    for skill in manager.skills:
        if not getattr(skill, "enabled", True):
            continue
        try:
            metadata = skill.tool_metadata()
        except Exception:
            metadata = []
        if not any(str(item.get("name", "")) == name for item in metadata):
            continue
        try:
            for fn in skill.get_tools():
                fn_name = getattr(fn, "name", None) or getattr(fn, "__name__", None)
                if fn_name == name:
                    return skill, fn
        except Exception:
            continue
    return None


def call_tool(name: str, args: Any = None) -> str:
    """Invoke one tool directly (no model, no tool schemas)."""
    found = find_tool(name)
    if found is None:
        return f"Unknown tool: {name}"
    _skill, fn = found
    target = getattr(fn, "func", None) or getattr(fn, "coroutine", None) or fn
    try:
        if args is None:
            result = target()
        elif isinstance(args, dict):
            result = target(**args)
        elif isinstance(args, list):
            result = target(*args)
        else:
            try:
                sig = inspect.signature(target)
                required = [
                    p
                    for p in sig.parameters.values()
                    if p.default is inspect.Parameter.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                ]
                result = target(args) if len(required) <= 1 else target()
            except (TypeError, ValueError):
                result = target(args)
        if inspect.isawaitable(result):
            result = asyncio.run(result)
        return str(result)
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Shell escape
# ---------------------------------------------------------------------------


def run_shell_command(command: str, console: Optional[Any] = None, cwd: Optional[str] = None) -> int:
    """
    Run `command` in a real shell, streaming output, and return the exit code.

    `!cd path` is handled in-process so a subsequent `!pwd` sees the new
    directory. Everything else is a one-shot `bash -c`; environment changes
    do not persist between commands.
    """
    command = (command or "").strip()
    if not command:
        if console:
            console.print("[dim]Usage: !<command>   e.g. !pwd, !git status[/dim]")
        return 0

    try:
        parts = command.split(None, 1)
        if parts[0] == "cd":
            target = os.path.expanduser(parts[1].strip()) if len(parts) > 1 else os.path.expanduser("~")
            os.chdir(target)
            if console:
                console.print(f"[dim]cwd: {os.getcwd()}[/dim]")
            return 0
    except Exception as exc:
        if console:
            console.print(f"[red]cd failed:[/red] {exc}")
        return 1

    if console:
        console.print(f"[dim]$ {command}[/dim]")
    try:
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=cwd or os.getcwd(),
        )
        for line in process.stdout or []:
            if console:
                console.print(line.rstrip("\n"), markup=False, highlight=False, soft_wrap=True)
            else:
                sys.stdout.write(line)
        code = process.wait()
    except KeyboardInterrupt:
        try:
            process.terminate()
        except Exception:
            pass
        if console:
            console.print("\n[yellow]Command cancelled.[/yellow]")
        return 130
    except Exception as exc:
        if console:
            console.print(f"[red]Shell error:[/red] {exc}")
        return 1

    if console:
        if code == 0:
            console.print("[dim]exit 0[/dim]")
        else:
            console.print(f"[red]exit {code}[/red]")
    return code
