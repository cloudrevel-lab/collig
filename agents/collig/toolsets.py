"""
Per-turn tool selection, ADK-native.

The LangChain agent narrowed its tool list by rebuilding the whole ReAct graph
on every message (``create_react_agent`` inside ``process_message``). ADK
supports the same narrowing as a first-class hook: a ``BaseToolset`` whose
``get_tools`` is consulted once per turn, with no graph rebuild.

The other change is where the tool list comes from. The old code matched
keywords to categories and then categories to a hand-written map of tool-name
prefixes, which had to be edited for every new skill and had already drifted
out of sync -- ``jira`` and ``web_search`` had keywords but no prefix entry, so
those tools never survived filtering, and half the listed prefixes (
``open_browser``, ``date_calculator``, ``create_diary``, ``select_from_menu``,
``cache_content``) named tools that no longer exist.

Here, keywords map to *skills* and the tools come from ``skill.get_tools()``.
A skill with no entry in ``SKILL_KEYWORDS`` contributes its own ``triggers``,
so a newly registered skill is reachable with no edit to this file.
"""
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.base_toolset import BaseToolset
from google.adk.tools.function_tool import FunctionTool

from core.runtime import get_skill_manager

# Patterns that indicate a trivial query needing no tools at all.
# Carried over unchanged -- it is a genuine saving, since it strips the whole
# tool-schema block from the request.
TRIVIAL_PATTERNS = [
    # Simple math: "1+1", "2 * 3", "100 / 5", "what is 2+2", "what's 1+1", etc.
    re.compile(r'^(what(?:\s*[\']s)?|calc(?:ulate)?|solve)\s*:?\s*\d+\s*[\+\-\*/x÷]\s*\d+', re.IGNORECASE),
    re.compile(r'^\d+\s*[\+\-\*/x÷]\s*\d+'),
    # Greetings
    re.compile(r'^(hi|hello|hey|greetings|good\s+(morning|afternoon|evening|day))\.?$', re.IGNORECASE),
    # Simple identity questions
    re.compile(r'^(who\s+are\s+you|what\s+are\s+you|what\s+(is|are)\s+your\s+(name|capabilities))\??$', re.IGNORECASE),
    # Thanks
    re.compile(r'^(thanks?|thank\s+you|thx|cheers|appreciate\s+it)\.?$', re.IGNORECASE),
]

# Extra intent keywords per skill, keyed by ``Skill.name``. These supplement
# each skill's own ``triggers`` rather than replacing them.
SKILL_KEYWORDS: Dict[str, List[str]] = {
    "Weather Reporter": ["weather", "temperature", "forecast", "rain", "sunny", "cold", "hot"],
    "Time": ["time", "clock", "timezone", "what time"],
    "News Search": ["news", "headlines", "latest news", "current events", "breaking news"],
    "Email Manager": ["email", "mail", "inbox", "send email", "check mail", "compose"],
    "File System Manager": ["file", "directory", "folder", "read file", "write file",
                            "create file", "list files", "delete file"],
    "Git Version Control": ["git", "commit", "push", "pull", "branch", "diff", "stash"],
    "Memory & Notes": ["note", "remember", "save note", "my notes", "search notes"],
    "Bookmarks": ["bookmark", "save link", "saved links", "favorites"],
    "Personal Profile": ["my name", "my info", "personal info", "set my name", "about me",
                         "remember this", "save this about", "my location", "my preference"],
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
    "jira": ["jira", "sprint", "my plate", "on my plate", "ticket", "tickets", "issue",
             "issues", "task", "tasks", "story", "stories", "backlog", "scrum", "agile", "board"],
}

# Offered when nothing else matches, so an open-ended message still has the
# handful of tools a general answer tends to want.
DEFAULT_SKILLS = ["Time", "Thinking Toggle", "Personal Profile"]

# Interactive skills prompt on the terminal via prompt_toolkit and would hang
# a browser session waiting for input that never arrives.
TERMINAL_ONLY_SKILLS = {"Menu", "Survey Automator"}


def is_trivial_query(message: str) -> bool:
    """True when a message plainly needs no tools (greeting, arithmetic, thanks)."""
    msg = (message or "").strip()
    return any(pattern.match(msg) for pattern in TRIVIAL_PATTERNS)


def text_of(context: Optional[ReadonlyContext]) -> str:
    """The text of the user message that started this invocation."""
    if context is None:
        return ""
    content = context.user_content
    if content is None or not content.parts:
        return ""
    return " ".join(part.text for part in content.parts if part.text)


def keywords_for(skill: Any) -> List[str]:
    """
    Intent keywords for a skill: its curated list plus its own triggers.

    Falling back to ``triggers`` is what lets an unlisted skill -- including
    one loaded at runtime from a SKILL.md -- still be matched.
    """
    words = list(SKILL_KEYWORDS.get(skill.name, []))
    words.extend(t.lower() for t in (skill.triggers or []))
    return words


class SkillToolset(BaseToolset):
    """
    Exposes the tools of whichever skills match the current message.

    Skills owned by a sub-agent are excluded, so the two selection mechanisms
    never both claim the same tool.
    """

    def __init__(self, exclude_skills: Optional[Iterable[str]] = None,
                 terminal: bool = True, **kwargs):
        """
        Args:
            exclude_skills: skill names handled by a sub-agent instead.
            terminal: False for browser surfaces, which drops the skills that
                block on terminal input.
        """
        super().__init__(**kwargs)
        self.exclude_skills: Set[str] = set(exclude_skills or ())
        if not terminal:
            self.exclude_skills |= TERMINAL_ONLY_SKILLS
        # FunctionTool construction parses the signature and docstring, so the
        # instances are cached by identity of the underlying function rather
        # than rebuilt each turn.
        self._tool_cache: Dict[int, FunctionTool] = {}

    def _wrap(self, fn: Any) -> FunctionTool:
        key = id(fn)
        cached = self._tool_cache.get(key)
        if cached is None:
            cached = FunctionTool(fn)
            self._tool_cache[key] = cached
        return cached

    def active_skills(self) -> List[Any]:
        """Enabled skills this toolset is responsible for."""
        return [
            skill for skill in get_skill_manager().skills
            if skill.enabled and skill.name not in self.exclude_skills
        ]

    def select_skills(self, message: str) -> List[Any]:
        """
        The skills relevant to ``message``.

        Empty for a trivial query, and empty again when the only matches are
        skills a specialist owns -- that turn is a pure transfer, so the root
        model needs no tools of its own beyond the transfer function ADK
        generates. When nothing matches at all, the default trio keeps an
        open-ended message from arriving tool-less.
        """
        if is_trivial_query(message):
            return []

        lowered = message.lower().strip()
        enabled = [s for s in get_skill_manager().skills if s.enabled]
        matched = [s for s in enabled if any(k in lowered for k in keywords_for(s))]
        if not matched:
            matched = [s for s in enabled if s.name in DEFAULT_SKILLS]
        return [s for s in matched if s.name not in self.exclude_skills]

    async def get_tools(
        self, readonly_context: Optional[ReadonlyContext] = None
    ) -> List[BaseTool]:
        """Tools for the current turn, narrowed to the matching skills."""
        message = text_of(readonly_context)
        if readonly_context is None:
            # No context (schema introspection, `adk web` startup): advertise
            # everything so the UI can list the full toolset.
            return self.all_tools()

        tools: List[BaseTool] = []
        for skill in self.select_skills(message):
            try:
                for fn in skill.get_tools():
                    tools.append(self._wrap(fn))
            except Exception:
                # A broken skill must not take down the whole turn.
                continue
        return tools

    def all_tools(self) -> List[BaseTool]:
        """Every tool this toolset could ever offer, ignoring the message."""
        tools: List[BaseTool] = []
        for skill in self.active_skills():
            try:
                for fn in skill.get_tools():
                    tools.append(self._wrap(fn))
            except Exception:
                continue
        return tools


def skill_tools(names: Sequence[str]) -> List[BaseTool]:
    """
    The tools of the named skills, as ADK tools.

    Used by the sub-agents, which own a fixed skill each and so need no
    per-turn selection.
    """
    wanted = set(names)
    tools: List[BaseTool] = []
    for skill in get_skill_manager().skills:
        if skill.name in wanted and skill.enabled:
            try:
                tools.extend(FunctionTool(fn) for fn in skill.get_tools())
            except Exception:
                continue
    return tools
