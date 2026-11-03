#!/usr/bin/env python3
"""
A tool the turn did not offer must not abort the message.

Reported failure: "最近澳洲有哪些新闻，给我讲一下" routed to no skill, so the
turn was offered only `transfer_to_agent`.  The model -- whose instructions
name `search_news` -- called it anyway, and ADK raised

    ValueError: Tool 'search_news' not found.  Available tools: transfer_to_agent

which failed the whole invocation.  `UnroutedToolPlugin` turns that into a
normal tool response: it runs the tool when this agent owns it, and otherwise
tells the model the capability is missing so it can answer in prose.
"""

from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

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


import core.harness as harness
from agents.collig.plugins import (
    UnroutedToolPlugin,
    _is_missing_tool_error,
)

# ---------------------------------------------------------------------------
# Only ADK's failed lookup is treated as "tool not offered"
# ---------------------------------------------------------------------------
_not_found = ValueError(
    "Tool 'search_news' not found.\nAvailable tools: transfer_to_agent\n\n"
    "Possible causes:\n  1. LLM hallucinated the function name"
)
check("ADK's lookup failure is recognised", _is_missing_tool_error(_not_found))
check(
    "ADK's placeholder tool is enough on its own",
    _is_missing_tool_error(ValueError("reworded"), SimpleNamespace(description="Tool not found")),
)
check(
    "a tool's own ValueError is not a lookup failure",
    not _is_missing_tool_error(ValueError("search_news failed: no results found")),
)
check("a tool's own assertion is not a lookup failure", not _is_missing_tool_error(RuntimeError("not found")))


# ---------------------------------------------------------------------------
# A fake registry: no network, and side effects we can observe
# ---------------------------------------------------------------------------
class _Skill:
    def __init__(self, name):
        self.name = name


calls = []


def _news(query: str) -> str:
    calls.append(("search_news", query))
    return f"Found 2 news items for '{query}'"


def _send(to: str) -> str:
    calls.append(("send_email", to))
    return "sent"


async def _weather(city: str) -> str:
    calls.append(("get_weather", city))
    return f"Weather for {city}: fine"


_FAKE_TOOLS = {
    "search_news": (_Skill("News Search"), _news),
    "send_email": (_Skill("Email Manager"), _send),
    "get_weather": (_Skill("Weather Reporter"), _weather),
}

_real_find_tool = harness.find_tool


def _fake_find_tool(name, manager=None):
    if name in _FAKE_TOOLS:
        return _FAKE_TOOLS[name]
    return _real_find_tool(name, manager)


harness.find_tool = _fake_find_tool


class _Context:
    """Just enough of a tool context for the plugin's agent-name check."""

    def __init__(self, agent_name="collig"):
        self._invocation = SimpleNamespace(agent=SimpleNamespace(name=agent_name))

    def get_invocation_context(self):
        return self._invocation


def _run(plugin, name, args=None, ctx=None):
    tool = SimpleNamespace(name=name)
    return asyncio.run(
        plugin.on_tool_error_callback(
            tool=tool,
            tool_args=args or {},
            tool_context=ctx or _Context(),
            error=_not_found,
        )
    )


_plugin = UnroutedToolPlugin(exclude_skills=["Email Manager", "Menu"], root_agent_name="collig")

# ---------------------------------------------------------------------------
# The root agent's own tool is run, so the user still gets an answer
# ---------------------------------------------------------------------------
calls.clear()
response = _run(_plugin, "search_news", {"query": "Australia news"})
check("an offered-but-unrouted tool is run", calls == [("search_news", "Australia news")], repr(calls))
check(
    "its result comes back as a function response",
    response is not None and "Found 2 news items" in response.get("result", ""),
    repr(response),
)

calls.clear()
response = _run(_plugin, "get_weather", {"city": "Sydney"})
check("an async tool is awaited", calls == [("get_weather", "Sydney")], repr(calls))
check("its result comes back too", "Weather for Sydney" in (response or {}).get("result", ""), repr(response))

# ---------------------------------------------------------------------------
# Side effects, specialists' skills and sub-agents are never run silently
# ---------------------------------------------------------------------------
calls.clear()
response = _run(_plugin, "send_email", {"to": "someone@example.com"})
check("a send is never run unoffered", calls == [], repr(calls))
check(
    "and the model is told plainly instead",
    "not available" in (response or {}).get("error", ""),
    repr(response),
)

calls.clear()
response = _run(_plugin, "delete_diary_entry", {"index": 1})
check("a delete is never run unoffered", calls == [], repr(calls))

calls.clear()
response = _run(_plugin, "search_news", {"query": "x"}, ctx=_Context("email_agent"))
check("a sub-agent cannot borrow the root's tools", calls == [], repr(calls))

calls.clear()
response = _run(_plugin, "no_such_tool")
check("a genuinely unknown tool is not run", calls == [], repr(calls))
check("an unknown tool gets the same plain answer", "not available" in (response or {}).get("error", ""))
check("every case returns a response instead of raising", response is not None)

# ---------------------------------------------------------------------------
# The app actually registers it, with the same exclusions as the toolset
# ---------------------------------------------------------------------------
from agents.collig.agent import APP_NAME, _excluded, app

_plugin_names = [getattr(p, "name", "") for p in app.plugins]
check("the plugin is on the app", "unrouted_tool_plugin" in _plugin_names, repr(_plugin_names))
_registered = next(p for p in app.plugins if getattr(p, "name", "") == "unrouted_tool_plugin")
check(
    "it shares the root toolset's exclusions",
    _registered.exclude_skills == set(_excluded),
    repr(_registered.exclude_skills),
)
check(
    "so it cannot run a specialist's tools",
    {"jira", "Email Manager", "Survey Automator"} <= _registered.exclude_skills,
    repr(_registered.exclude_skills),
)
check("it is scoped to the root agent", _registered.root_agent_name == APP_NAME)

# ---------------------------------------------------------------------------
print("\n================ SUMMARY ================")
print("%d passed, %d failed" % (len(passed), len(failed)))
if failed:
    for name in failed:
        print("  -", name)
    sys.exit(1)
print("All checks passed.")
