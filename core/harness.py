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
    re.compile(r"^(你好|您好|嗨|哈喽|早上好|早安|下午好|晚上好|在吗)[!！。.？?]*$"),
    # Simple identity questions
    re.compile(r"^(who\s+are\s+you|what\s+are\s+you|what\s+(is|are)\s+your\s+(name|capabilities))\??$", re.IGNORECASE),
    re.compile(r"^(你是谁|你叫什么|你能做什么)[?？]?$"),
    # Thanks
    re.compile(r"^(thanks?|thank\s+you|thx|cheers|appreciate\s+it)\.?$", re.IGNORECASE),
    re.compile(r"^(谢谢|多谢|感谢|好的?谢谢|辛苦了)[!！。.]*$"),
]

# Extra intent keywords per skill, keyed by `Skill.name`.  These supplement
# each skill's own triggers rather than replacing them.
#
# The lists carry Chinese as well as English terms because the router is the
# only thing that decides which tools the model may call, and a user who asks
# in Chinese was getting no tools at all: "最近澳洲有哪些新闻" matched nothing,
# the model was offered only `transfer_to_agent`, and when it called the
# `search_news` its instructions name the turn died with
# `Tool 'search_news' not found`.  A keyword list that only speaks one
# language silently gates a whole language out of the tool catalogue.
SKILL_KEYWORDS: Dict[str, List[str]] = {
    "Weather Reporter": [
        "weather",
        "temperature",
        "forecast",
        "rain",
        "sunny",
        "cold",
        "hot",
        "天气",
        "气温",
        "温度",
        "预报",
        "下雨",
        "冷不冷",
        "热不热",
    ],
    "Time": ["time", "clock", "timezone", "what time", "几点", "时间", "时区"],
    "News Search": [
        "news",
        "headlines",
        "latest news",
        "current events",
        "breaking news",
        "新闻",
        "头条",
        "时事",
        "资讯",
        "要闻",
    ],
    "Email Manager": [
        "email",
        "mail",
        "inbox",
        "send email",
        "check mail",
        "compose",
        "邮件",
        "邮箱",
        "收件箱",
        "发邮件",
    ],
    "File System Manager": [
        "file",
        "directory",
        "folder",
        "read file",
        "write file",
        "create file",
        "list files",
        "delete file",
        "文件",
        "文件夹",
        "目录",
    ],
    "Git Version Control": ["git", "commit", "push", "pull", "branch", "diff", "stash", "分支", "提交", "代码库"],
    "Memory & Notes": ["note", "remember", "save note", "my notes", "search notes", "笔记", "记一下", "记住", "记事"],
    "Bookmarks": ["bookmark", "save link", "saved links", "favorites", "书签", "收藏"],
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
        "我的名字",
        "我的信息",
        "个人信息",
        "关于我",
        "我住在",
    ],
    "System Info": ["system status", "disk space", "memory usage", "install", "package", "系统状态", "磁盘", "内存"],
    "Chinese Lunar Calendar": ["lunar", "chinese calendar", "chinese date", "农历", "阴历", "黄历"],
    "Date Calculator": [
        "days between",
        "date calculator",
        "what date",
        "add days",
        "subtract days",
        "相差几天",
        "几天后",
        "日期计算",
    ],
    "Cache": ["cache", "cached", "缓存"],
    "Browser": ["open browser", "open website", "launch browser", "browse", "浏览器", "打开网页"],
    "Menu": ["menu", "select from", "choose from", "菜单"],
    "Survey Automator": ["survey", "questionnaire", "form", "问卷", "调查"],
    "Thinking Toggle": ["hide thinking", "show thinking", "toggle thinking", "隐藏思考", "显示思考"],
    "Diary": ["diary", "create a diary", "diary entry", "my diary", "日记"],
    "Web Search": [
        "search",
        "look up",
        "find information",
        "google",
        "search the web",
        "web search",
        "搜索",
        "搜一下",
        "上网查",
    ],
    "Flight Search": [
        "flight",
        "flights",
        "airfare",
        "air fare",
        "air ticket",
        "air tickets",
        "plane ticket",
        "plane tickets",
        "flight search",
        "cheapest flight",
        "round trip",
        "round-trip",
        "one way",
        "one-way",
        "fly to",
        "flying to",
        "skyscanner",
        "google flights",
        "airline",
        "航班",
        "机票",
        "飞机票",
        "飞机",
        "机场",
        "航空",
        "转机",
        "中转",
        "直飞",
        "经济舱",
        "商务舱",
        "头等舱",
        "往返",
        "单程",
        "飞往",
        "航线",
    ],
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
        "工单",
        "看板",
    ],
}

# Skills that are always safe to expose on an open-ended turn.  Deliberately
# empty: a poem or a chat message needs zero tool schemas, which is the whole
# point of per-turn selection.
DEFAULT_SKILLS: List[str] = []

# Messages that only make sense against the previous turn: an acceptance of
# what the assistant just offered ("ok", "yes", "go ahead"), or a request that
# points back at it ("the rest of the week", "what about tomorrow?").  Routing
# these on their own words alone is what made the assistant answer "ok" with
# "Anything else?" -- it had no `get_weather` to continue with.  See
# `route_with_context`.
FOLLOWUP_PATTERNS = [
    # Acceptances / continuations, optionally with a short tail
    # ("ok go ahead", "yes please", "sure, do it").
    re.compile(
        r"^(ok(ay)?|k|yes|yeah|yep|yup|sure|alright|right|fine|please|"
        r"go\s+ahead|go\s+on|continue|proceed|do\s+it|do\s+that|do\s+so|"
        r"sounds\s+good|that\s+works|why\s+not|of\s+course|exactly|correct|"
        r"agreed|perfect|great|nice|good)(\b.*)?$",
        re.IGNORECASE,
    ),
    # Continuations that point at the previous turn.
    re.compile(
        r"^(and|also|then|now|so|what\s+about|how\s+about|same|more|" r"check|show\s+me|tell\s+me|give\s+me)\b",
        re.IGNORECASE,
    ),
    # Ranges that reuse the previous subject without naming it.
    re.compile(
        r"\b(rest\s+of\s+the\s+(week|day|month)|the\s+week|this\s+week|"
        r"next\s+few\s+days|coming\s+days|the\s+same|as\s+well)\b",
        re.IGNORECASE,
    ),
    # Answers that supply a parameter the previous turn asked for.  After
    # "tell me your city", the reply "the location is Oatlands NSW 2117" routes
    # to no skill on its own; without this the model still calls the previous
    # turn's `get_weather` but the toolset has removed it, and ADK fails with
    # "Tool 'get_weather' not found".
    re.compile(
        r"^(?:the\s+|my\s+|our\s+)?" r"(?:location|city|suburb|town|place|address|postcode|zip)\s*(?:is|:|=|-)\s*\S",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:in|at|near|around|from)\s+"
        r"(?!other\b|general\b|fact\b|short\b|my\s+opinion\b|a\s+minute\b)[A-Za-z0-9]",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:use|try|change\s+(?:it|that)\s+to|set\s+(?:it|that)\s+to|make\s+it)\s+\S",
        re.IGNORECASE,
    ),
    re.compile(r"^(?:it'?s|that'?s|i'?m|i\s+am|we'?re|we\s+are)\s+(?:in|at|from|near)\s+\S", re.IGNORECASE),
    # A bare place + postcode ("Oatlands NSW 2117") or just the postcode.
    re.compile(r"^[A-Za-z][A-Za-z .'-]{1,50}\b\d{4,5}$", re.IGNORECASE),
    re.compile(r"^\d{4,5}$"),
    # Chinese acceptances and continuations: "好的", "可以，继续", "还有呢".
    # Same job as the English acceptance pattern above -- without it a
    # Chinese-speaking user's "好的" routes to nothing and the model loses
    # the tool it just offered to use.
    re.compile(
        r"^(好的?|好吧|行|可以|没问题|嗯+|哦+|对|是的?|继续|接着|往下|"
        r"然后|还有|再说|来说|就来|看一下|查一下|就这样|开始吧|辛苦了?)"
    ),
    # Chinese "and ...?" / "what about ...?" tails that point back at the
    # previous turn rather than naming a new subject.
    re.compile(r"(呢|怎么样|如何)[?？]?$"),
]

# Pronouns and deictic references ("is it going to rain?", "how about that
# one?"). Too common in fresh questions to count on their own, so they only
# mark a follow-up when the message is short enough to be a reply.
_REFERENCE_PATTERN = re.compile(r"\b(it|that|those|them|too|here|there)\b", re.IGNORECASE)
_REFERENCE_MAX_WORDS = 8

_GREETING_PATTERN = re.compile(
    r"^(hi|hello|hey|yo|howdy|greetings|good\s+(morning|afternoon|evening|day)|"
    r"morning|afternoon|evening|你好|您好|嗨|哈喽|早上好|早安|下午好|晚上好)\b",
    re.IGNORECASE,
)


def is_trivial_query(message: str) -> bool:
    """True when a message plainly needs no tools (greeting, arithmetic, thanks)."""
    msg = (message or "").strip()
    return any(pattern.match(msg) for pattern in TRIVIAL_PATTERNS)


def is_greeting(message: str) -> bool:
    """
    True for a bare greeting.

    Kept separate from ``is_trivial_query`` because greetings are the one
    trivial turn that may still need a tool: a due routine ("they check the
    news every morning") should be acted on when the user says hello.
    "Morning meeting notes" starts with a greeting but is a work request, so a
    few scheduling words disqualify it.
    """
    msg = (message or "").strip()
    lowered = msg.lower()
    if any(word in lowered for word in ("meeting", "standup", "stand-up", "agenda", "schedule", "calendar")):
        return False
    return bool(_GREETING_PATTERN.match(msg))


def is_followup_message(message: str) -> bool:
    """
    True when a message is a reply to the previous turn rather than a new topic.

    Used to carry the previous turn's skills into this one: the routing is
    keyword-based and deliberately narrow, so ``ok`` and ``the rest of the
    week`` match no skill at all on their own even though the conversation --
    and the offer the assistant just made -- make the intent unambiguous.
    """
    msg = (message or "").strip()
    if not msg:
        return False
    if any(pattern.search(msg) for pattern in FOLLOWUP_PATTERNS):
        return True
    words = re.findall(r"[A-Za-z0-9']+", msg)
    return len(words) <= _REFERENCE_MAX_WORDS and bool(_REFERENCE_PATTERN.search(msg))


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


_CJK_RANGES = (
    ("\u3040", "\u30ff"),  # hiragana + katakana
    ("\u3400", "\u4dbf"),  # CJK extension A
    ("\u4e00", "\u9fff"),  # CJK unified ideographs
    ("\uac00", "\ud7af"),  # hangul syllables
)


def has_cjk(text: str) -> bool:
    """True when `text` contains a script that is written without spaces."""
    return any(lo <= ch <= hi for ch in text for lo, hi in _CJK_RANGES)


def _keyword_score(message: str, keyword: str) -> int:
    """
    Weighted match: exact phrase > multi-word phrase > single word.

    CJK keywords are matched by substring only.  ``\\b`` is defined against
    "word characters", and every ideograph is one, so a Chinese keyword in
    Chinese text sits between two word characters and never has a boundary --
    ``re.search(r"\\b新闻\\b", "最近澳洲有哪些新闻")`` finds nothing.  Since the
    language has no spaces to match against, presence is the whole signal.
    """
    keyword = (keyword or "").strip().lower()
    if not keyword:
        return 0
    if keyword == message:
        return 10
    if keyword not in message:
        return 0
    if " " in keyword:
        return 5
    if has_cjk(keyword):
        # A two-character term is already specific; a longer one is stronger.
        return 3 if len(keyword) >= 3 else 2
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
    # Skills kept from the previous turn because this message is a follow-up.
    carried: bool = False

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
        suffix = " · 1 tool" if self.tool_count == 1 else f" · {self.tool_count} tools"
        if self.carried:
            suffix += " (kept from previous turn)"
        return f"{names}{suffix}"


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


def route_with_context(
    message: str,
    previous_message: Optional[Any] = None,
    manager: Optional[Any] = None,
    exclude: Optional[Iterable[str]] = None,
) -> Route:
    """
    Route a message, keeping the previous turn's skills when it is a follow-up.

    ``route_message`` only sees the current text, which is right for a new
    topic and wrong for a reply: after "what's the weather tomorrow ..." the
    message "ok" scores no skill at all, so the model was handed zero tools
    and could not carry out the "rest of the week" it had just offered.

    For messages that are clearly replies (`is_followup_message`), the skills
    of the previous user turn are merged in rather than replacing the ones
    this message matched.  That keeps a topic change inside a follow-up ("now
    check the news") working while making short acceptances act on what was
    offered.  The union is bounded by the previous turn's skills, which the
    router already keeps to one or two, so no turn suddenly gets all 58 tools.

    ``previous_message`` may be a single earlier user message or a sequence of
    them, nearest first.  The first one that routes to a skill wins, so a
    chain of acceptances ("... weather" -> "ok" -> "ok") keeps the subject
    instead of looking only as far back as the previous "ok".
    """
    route = route_message(message, manager=manager, exclude=exclude)
    if route.trivial or not previous_message or not is_followup_message(message):
        return route

    candidates = [previous_message] if isinstance(previous_message, str) else list(previous_message)
    for candidate in candidates:
        carried = route_message(candidate, manager=manager, exclude=exclude)
        if not carried.skills:
            continue
        names = {str(getattr(s, "name", "")) for s in route.skills}
        skills = list(route.skills) + [s for s in carried.skills if str(getattr(s, "name", "")) not in names]
        scores = dict(route.scores)
        for name, score in carried.scores.items():
            scores.setdefault(name, score)
        return Route(
            message=message,
            skills=skills,
            scores=scores,
            reason="follow-up",
            carried=True,
        )
    return route


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
    "distill",
    "chatto",
    "personality",
    "memory",
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


def _coerce_scalar(value: Any, annotation: Any) -> Any:
    """Coerce a CLI string argument to the tool parameter's declared type."""
    target = annotation
    if isinstance(target, str):
        target = {"int": int, "float": float, "bool": bool, "str": str}.get(target, target)
    try:
        if target is int:
            return int(str(value).strip())
        if target is float:
            return float(str(value).strip())
        if target is bool:
            return str(value).strip().lower() in ("1", "true", "yes", "on")
        if target is str:
            return str(value)
    except (TypeError, ValueError):
        return value
    return value


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
                positional = [
                    p for p in sig.parameters.values() if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                ]
                if positional:
                    result = target(_coerce_scalar(args, positional[0].annotation))
                else:
                    result = target()
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
