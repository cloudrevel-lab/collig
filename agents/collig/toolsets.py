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

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.base_toolset import BaseToolset
from google.adk.tools.function_tool import FunctionTool

# `is_trivial_query` and `text_of` are also imported from here by
# `agents.collig.plugins`; keep the re-export.
from core.harness import is_greeting, is_trivial_query, route_with_context, text_of  # noqa: F401
from core.runtime import get_skill_manager
from skills.tooling import as_adk_function

TERMINAL_ONLY_SKILLS = {"Menu", "Survey Automator"}


def _previous_user_messages(readonly_context: ReadonlyContext, limit: int = 3) -> List[str]:
    """
    Recent user messages before this turn, nearest first, from the ADK session.

    Function responses are also authored ``user`` but carry no text, so they
    are skipped. The current message is skipped too: ADK appends it to the
    session before the toolset is consulted, so without this the "previous"
    message would be the message being routed. More than one is returned so a
    chain of follow-ups ("... weather" -> "ok" -> "ok") can still find the turn
    that named the subject.
    """
    current = text_of(readonly_context).strip()
    found: List[str] = []
    try:
        events = readonly_context.session.events or []
    except Exception:
        return found
    for event in reversed(events):
        if getattr(event, "author", None) != "user":
            continue
        content = getattr(event, "content", None)
        parts = getattr(content, "parts", None) or []
        if any(getattr(part, "function_response", None) for part in parts):
            continue
        text = " ".join(part.text for part in parts if getattr(part, "text", None)).strip()
        if text and text != current:
            found.append(text)
            if len(found) >= limit:
                break
    return found


class SkillToolset(BaseToolset):
    """
    Exposes the tools of whichever skills match the current message.

    Skills owned by a sub-agent are excluded, so the two selection mechanisms
    never both claim the same tool.
    """

    def __init__(self, exclude_skills: Optional[Iterable[str]] = None, terminal: bool = True, **kwargs):
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
            cached = FunctionTool(as_adk_function(fn))
            self._tool_cache[key] = cached
        return cached

    def active_skills(self) -> List[Any]:
        """Enabled skills this toolset is responsible for."""
        return [
            skill for skill in get_skill_manager().skills if skill.enabled and skill.name not in self.exclude_skills
        ]

    def select_skills(self, message: str, previous_messages: Sequence[str] = ()) -> List[Any]:
        """
        The skills relevant to ``message``, in the light of the previous turns.

        Empty for a trivial query, and empty again when the only matches are
        skills a specialist owns -- that turn is a pure transfer, so the root
        model needs no tools of its own beyond the transfer function ADK
        generates.  A follow-up ("ok", "the rest of the week", "what about
        tomorrow?") also keeps the skills of the previous user message: its
        own words match nothing, so dropping them left the model unable to do
        the thing it had just offered to do.
        """
        if isinstance(previous_messages, str):  # tolerate a single message
            previous_messages = [previous_messages]
        return route_with_context(
            message,
            previous_message=list(previous_messages),
            exclude=self.exclude_skills,
        ).skills

    async def get_tools(self, readonly_context: Optional[ReadonlyContext] = None) -> List[BaseTool]:
        """Tools for the current turn, narrowed to the matching skills."""
        if readonly_context is None:
            # No context (schema introspection, `adk web` startup): advertise
            # everything so the UI can list the full toolset.
            return self.all_tools()

        message = text_of(readonly_context)
        skills = self.select_skills(message, _previous_user_messages(readonly_context))
        if not skills and is_greeting(message) and len(message.split()) <= 12:
            skills = self._routine_skills()
        tools: List[BaseTool] = []
        for skill in skills:
            try:
                for fn in skill.get_tools():
                    tools.append(self._wrap(fn))
            except Exception:
                # A broken skill must not take down the whole turn.
                continue
        return tools

    def _routine_skills(self) -> List[Any]:
        """
        The skill for a routine that is due right now, if the user greets us.

        This is what makes "they always check AI news in the morning" real:
        the greeting turn would otherwise route to no skill at all and the
        model would have no tool to act on the memory.  The memory block in
        the instruction tells the model why the tool is there.
        """
        try:
            from core.user_memory import get_user_memory

            routine = get_user_memory().due_routine()
            skill_name = (routine or {}).get("skill")
            if not skill_name or skill_name in self.exclude_skills:
                return []
            skill = get_skill_manager().get_skill_by_name(str(skill_name))
            if skill is None or not skill.enabled:
                return []
            return [skill]
        except Exception:
            return []

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
                tools.extend(FunctionTool(as_adk_function(fn)) for fn in skill.get_tools())
            except Exception:
                continue
    return tools
