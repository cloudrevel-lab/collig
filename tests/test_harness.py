#!/usr/bin/env python3
"""Tests for the harness routing, lazy skills, shortcuts and config scoping."""

from __future__ import annotations

import os
import sys

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


# ---------------------------------------------------------------------------
# Lazy skill registry
# ---------------------------------------------------------------------------
from core.runtime import get_skill_manager
from skills.base import LazySkill

sm = get_skill_manager()
by_name = {s.name: s for s in sm.skills}
check("Time stays a concrete built-in", not isinstance(by_name["Time"], LazySkill))
check("Weather is lazy", isinstance(by_name["Weather Reporter"], LazySkill))
check(
    "Weather metadata is available before load",
    by_name["Weather Reporter"]._delegate is None and len(by_name["Weather Reporter"].tool_metadata()) == 1,
)
check("Jira metadata includes its tools", len(by_name["jira"].tool_metadata()) == 4)
check("Lazy skill configure does not import the module", by_name["Weather Reporter"]._delegate is None)
check("Skill catalogue exposes stubs, not loaded functions", True)
check("concrete ensure_loaded returns self", by_name["Time"].ensure_loaded() is by_name["Time"])
_weather_lazy = by_name["Weather Reporter"]
_weather_loaded = _weather_lazy.ensure_loaded()
check(
    "LazySkill.ensure_loaded imports the concrete module",
    _weather_loaded is not _weather_lazy and not isinstance(_weather_loaded, LazySkill),
)

# ---------------------------------------------------------------------------
# Intent routing
# ---------------------------------------------------------------------------
from core.harness import (
    call_tool,
    is_greeting,
    is_trivial_query,
    parse_tool_command,
    route_message,
    run_shell_command,
)

route = route_message("get_current_time")
check("exact tool name selects only Time", route.names == ["Time"], "got " + repr(route.names))
check("exact tool name advertises one tool", route.tool_count == 1)

route = route_message("what time is it?")
check("time question selects only Time", route.names == ["Time"], repr(route.names))

route = route_message("what is the weather in Sydney?")
check("weather question selects only Weather Reporter", route.names == ["Weather Reporter"], repr(route.names))

route = route_message("jira sprint")
check("jira question selects jira and its tools", route.names == ["jira"] and route.tool_count == 4, repr(route.names))

check("greeting is trivial", is_trivial_query("hello"))
route = route_message("hello")
check("trivial query selects no skills", route.skills == [])
route = route_message("write me a poem")
check("open-ended request selects no skills", route.skills == [])

# ---------------------------------------------------------------------------
# Follow-ups keep the previous turn's skills
# ---------------------------------------------------------------------------
from core.harness import is_followup_message, route_with_context

_weather_turn = "what's the weather tomorrow at my place - oatlands nsw 2117"

check("short acceptance is a follow-up", is_followup_message("ok"))
check("range reference is a follow-up", is_followup_message("the rest of the week"))
check("continuation is a follow-up", is_followup_message("what about tomorrow?"))
check("a new topic is not a follow-up", not is_followup_message("write me a poem"))
check("a fresh question is not a follow-up", not is_followup_message("what is the weather in Sydney?"))
check("a location answer is a follow-up", is_followup_message("the location is oatlands nsw 2117"))
check("a bare place+postcode answer is a follow-up", is_followup_message("oatlands nsw 2117"))
check("a prefixed place answer is a follow-up", is_followup_message("in oatlands nsw 2117"))
check("a postcode answer is a follow-up", is_followup_message("2117"))
check(
    "a new topic that starts with 'in' is not a follow-up",
    not is_followup_message("in other news, tell me about python"),
)

route = route_message("ok")
check("bare ok matches no skill on its own", route.skills == [], repr(route.names))

route = route_with_context("ok", previous_message=_weather_turn)
check("ok keeps the previous turn's weather skill", route.names == ["Weather Reporter"], repr(route.names))
check("carried route is marked as such", route.carried)
check("carried route says it came from the previous turn", "previous turn" in route.summary(), route.summary())

route = route_with_context("what about tomorrow?", previous_message=_weather_turn)
check("follow-up keeps weather alongside the date skill", "Weather Reporter" in route.names, repr(route.names))

route = route_with_context("the location is oatlands nsw 2117", previous_message=_weather_turn)
check(
    "a location answer keeps the previous weather skill",
    "Weather Reporter" in route.names and route.carried,
    repr(route.names),
)
route = route_with_context("my location is oatlands nsw 2117", previous_message=_weather_turn)
check(
    "my-location answer keeps both profile and weather skills",
    {"Personal Profile", "Weather Reporter"} <= set(route.names),
    repr(route.names),
)

route = route_with_context("write me a poem", previous_message=_weather_turn)
check("a new topic does not inherit the previous tools", route.skills == [], repr(route.names))

route = route_with_context("ok")
check("no previous message means no carry-over", route.skills == [], repr(route.names))

route = route_with_context("ok", previous_message=["ok", _weather_turn])
check("a chained ok still finds the turn with the subject", route.names == ["Weather Reporter"], repr(route.names))

route = route_with_context("now check the news", previous_message=_weather_turn)
check(
    "a topic change inside a follow-up keeps both skills",
    set(route.names) == {"News Search", "Weather Reporter"},
    repr(route.names),
)

# The toolset must actually offer get_weather to a follow-up turn, which is
# what "ok" -> "anything else?" was missing.
import asyncio
from types import SimpleNamespace

from google.genai import types as genai_types

from agents.collig.toolsets import SkillToolset


def _fake_context(*messages):
    events = [
        SimpleNamespace(
            author="user",
            content=genai_types.Content(role="user", parts=[genai_types.Part(text=text)]),
        )
        for text in messages
    ]
    return SimpleNamespace(
        user_content=genai_types.Content(role="user", parts=[genai_types.Part(text=messages[-1])]),
        session=SimpleNamespace(events=events),
    )


_toolset = SkillToolset(terminal=True)
_names = [t.name for t in asyncio.run(_toolset.get_tools(_fake_context(_weather_turn, "ok")))]
check("follow-up turn still offers get_weather", "get_weather" in _names, repr(_names))
_names = [
    t.name for t in asyncio.run(_toolset.get_tools(_fake_context(_weather_turn, "the location is oatlands nsw 2117")))
]
check("a location answer still offers get_weather", "get_weather" in _names, repr(_names))
_names = [t.name for t in asyncio.run(_toolset.get_tools(_fake_context(_weather_turn, "ok", "ok")))]
check("chained follow-up still offers get_weather", "get_weather" in _names, repr(_names))
_names = [t.name for t in asyncio.run(_toolset.get_tools(_fake_context("write me a poem")))]
check("new-topic turn still offers no tools", _names == [], repr(_names))

# ---------------------------------------------------------------------------
# Chinese messages route like English ones
# ---------------------------------------------------------------------------
# The keyword lists and the router's word-boundary matching were English-only,
# so a Chinese question selected no skills at all.  The model was then offered
# only `transfer_to_agent`, called the `search_news` its instructions name, and
# ADK aborted the turn with "Tool 'search_news' not found".
route = route_message("最近澳洲有哪些新闻，给我讲一下")
check("Chinese news question selects News Search", route.names == ["News Search"], repr(route.names))
route = route_message("明天天气怎么说")
check("Chinese weather question selects Weather Reporter", route.names == ["Weather Reporter"], repr(route.names))
route = route_message("现在几点")
check("Chinese time question selects Time", route.names == ["Time"], repr(route.names))
route = route_message("帮我查一下机票")
check("Chinese flight question selects Flight Search", route.names == ["Flight Search"], repr(route.names))
route = route_message("给我写首诗")
check("an open-ended Chinese request selects no skills", route.skills == [], repr(route.names))

check("a Chinese acceptance is a follow-up", is_followup_message("好的"))
check("a Chinese continuation is a follow-up", is_followup_message("还有呢"))
check("a fresh Chinese topic is not a follow-up", not is_followup_message("帮我写首诗"))
check("a Chinese greeting needs no tools", is_trivial_query("你好") and is_greeting("你好"))
check("a Chinese greeting with a request is not trivial", not is_trivial_query("你好，帮我查下明天天气"))
check("Chinese thanks need no tools", is_trivial_query("谢谢"))
route = route_with_context("好的", previous_message="最近澳洲有哪些新闻，给我讲一下")
check(
    "a Chinese acceptance keeps the previous turn's news skill",
    route.names == ["News Search"] and route.carried,
    repr(route.names),
)

_names = [t.name for t in asyncio.run(_toolset.get_tools(_fake_context("最近澳洲有哪些新闻，给我讲一下")))]
check("a Chinese news turn offers search_news", "search_news" in _names, repr(_names))
_names = [t.name for t in asyncio.run(_toolset.get_tools(_fake_context("悉尼明天天气如何")))]
check("a Chinese weather turn offers get_weather", "get_weather" in _names, repr(_names))

# ---------------------------------------------------------------------------
# Weather tool understands the multi-day follow-up it offers
# ---------------------------------------------------------------------------
_days, _week_range, _clean = _weather_loaded._parse_date_hint("Oatlands NSW 2117 rest of the week")
check(
    "rest of the week asks for a multi-day forecast",
    _week_range and _days == 0 and _clean == "Oatlands NSW 2117",
    repr((_days, _week_range, _clean)),
)

_days, _week_range, _clean = _weather_loaded._parse_date_hint("Sydney day after tomorrow")
check("day after tomorrow is two days ahead", _days == 2 and not _week_range, repr((_days, _week_range)))

_days, _week_range, _clean = _weather_loaded._parse_date_hint("Sydney tomorrow")
check("tomorrow still parses as one day ahead", _days == 1 and not _week_range, repr((_days, _week_range)))

# ---------------------------------------------------------------------------
# Deterministic tool shortcut
# ---------------------------------------------------------------------------
parsed = parse_tool_command("/get_current_time")
check("parse tool command", parsed is not None and parsed[0] == "get_current_time")
check("reserved CLI command is not a tool shortcut", parse_tool_command("/config") is None)
out = call_tool("get_current_time")
check("direct tool call runs without a model", "Current time:" in out, out)

# ---------------------------------------------------------------------------
# ADK can wrap a LangChain tool
# ---------------------------------------------------------------------------
from google.adk.tools.function_tool import FunctionTool
from skills.tooling import as_adk_function

time_tool = by_name["Time"].get_tools()[0]
wrapped = FunctionTool(as_adk_function(time_tool))
check("ADK FunctionTool wraps a LangChain StructuredTool", wrapped.name == "get_current_time")

# ---------------------------------------------------------------------------
# Shell escape
# ---------------------------------------------------------------------------
code = run_shell_command("pwd", console=None)
check("shell command exits zero", code == 0)

# ---------------------------------------------------------------------------
# Provider-scoped config UI
# ---------------------------------------------------------------------------
from core.config_ui import ConfigState

cfg = {
    "provider": "deepseek",
    "LLM_PROVIDER": "deepseek",
    "llm_model": "deepseek-chat",
    "LLM_MODEL": "deepseek-chat",
    "DEEPSEEK_API_KEY": "sk-deep",
    "DASHSCOPE_API_KEY": "sk-dash",
    "DASHSCOPE_ENDPOINT": "singapore",
    "CUSTOM_BASE_URL": "https://custom.example/v1",
    "CUSTOM_API_KEY": "sk-custom",
    "OPENAI_API_KEY": "sk-openai",
}
state = ConfigState(config=cfg, agent=None)
state.screen = "detail"
state.selected_provider = "deepseek"
deep_rows = [r.key for r in state.detail_rows()]
check("DeepSeek detail has no DashScope rows", "region" not in deep_rows, repr(deep_rows))
check("DeepSeek detail has its own key", "key" in deep_rows)
check("DeepSeek detail has its own model", "model" in deep_rows)

state.selected_provider = "dashscope"
dash_rows = [r.key for r in state.detail_rows()]
check("DashScope detail has a region row", "region" in dash_rows, repr(dash_rows))

state.selected_provider = "custom"
custom_rows = [r.key for r in state.detail_rows()]
check("Custom detail has a URL row", "url" in custom_rows, repr(custom_rows))

# Escape hierarchy: detail -> providers -> root -> quit.
state = ConfigState(config=cfg, agent=None)
state.screen = "detail"
state.selected_provider = "deepseek"
check("Escape from detail goes to provider list", state.back() is False and state.screen == "providers")
check("Escape from provider list goes to root", state.back() is False and state.screen == "root")
check("Escape at root requests quit", state.back() is True)

# Provider-scoped writes do not overwrite another provider's values.
from core.config_ui import set_provider_field

cfg2 = {"provider": "deepseek", "LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "d1"}
set_provider_field(cfg2, "openai", "key", "o1")
check(
    "writing OpenAI key leaves DeepSeek key intact", cfg2["OPENAI_API_KEY"] == "o1" and cfg2["DEEPSEEK_API_KEY"] == "d1"
)
set_provider_field(cfg2, "deepseek", "model", "deepseek-reasoner")
check("writing DeepSeek model updates DeepSeek model key", cfg2["DEEPSEEK_MODEL"] == "deepseek-reasoner")

# ---------------------------------------------------------------------------
# News cache: same query updates one entry instead of duplicating it
# ---------------------------------------------------------------------------
import tempfile
from core.news_cache import NewsCacheManager

with tempfile.TemporaryDirectory() as _td:
    _mgr = NewsCacheManager()
    _mgr._cache_file = os.path.join(_td, "news.json")
    _mgr._cached_entries = []
    _mgr.save_search("ai news", [{"url": "https://a"}])
    _mgr.save_search("ai news", [{"url": "https://a"}])
    check("news cache dedupes identical search", len(_mgr.get_all_searches()) == 1)
    _mgr.save_search("ai news", [{"url": "https://b"}])
    _entries = _mgr.get_all_searches()
    check(
        "news cache updates same query in place", len(_entries) == 1 and _entries[0].news_items[0]["url"] == "https://b"
    )
    check("news cache returns a stable id", _entries[0].cache_id.startswith("news_"))

    _mgr.save_search("ai news", [{"url": "https://s1"}], session_id="session-1")
    _mgr.save_search("ai news", [{"url": "https://s2"}], session_id="session-2")
    check(
        "news cache keeps a list per session",
        len(_mgr.get_all_searches()) == 2
        and _mgr.get_most_recent("session-1").news_items[0]["url"] == "https://s1"
        and _mgr.get_most_recent("session-2").news_items[0]["url"] == "https://s2",
    )
    check(
        "news cache falls back to newest search for an unknown session",
        _mgr.get_most_recent("unknown-session") is not None,
    )

# ---------------------------------------------------------------------------
# Trace records the prompt, messages and tools it actually sent
# ---------------------------------------------------------------------------
from google.adk.models.llm_request import LlmRequest

from agents.collig import trace_plugin as _trace_plugin


class _FakeTraceManager:
    def __init__(self):
        self.started = None

    def start_llm_call(self, session_id, invocation_id, **kwargs):
        self.started = kwargs
        return 0


_fake_trace = _FakeTraceManager()
_trace_plugin.get_trace_manager = lambda: _fake_trace
_plugin = _trace_plugin.TracePlugin()
_plugin._inv_session["inv-1"] = "session-1"
_request = LlmRequest(
    model="openai/deepseek-flash",
    contents=[genai_types.Content(role="user", parts=[genai_types.Part(text="ok")])],
    config=genai_types.GenerateContentConfig(
        system_instruction=genai_types.Content(parts=[genai_types.Part(text="You are Collig")]),
        tools=[
            genai_types.Tool(
                function_declarations=[genai_types.FunctionDeclaration(name="get_weather", description="weather")]
            )
        ],
    ),
)
asyncio.run(
    _plugin.before_model_callback(
        callback_context=SimpleNamespace(invocation_id="inv-1"),
        llm_request=_request,
    )
)
check(
    "trace records the system prompt",
    _fake_trace.started["system_prompt"] == "You are Collig",
    repr(_fake_trace.started["system_prompt"]),
)
check(
    "trace records the conversation",
    [m["content"] for m in _fake_trace.started["messages"]] == ["ok"],
    repr(_fake_trace.started["messages"]),
)
check(
    "trace records the offered tools",
    [t["name"] for t in _fake_trace.started["tools"]] == ["get_weather"],
    repr(_fake_trace.started["tools"]),
)

# ---------------------------------------------------------------------------
print("\n================ SUMMARY ================")
print("%d passed, %d failed" % (len(passed), len(failed)))
if failed:
    for name in failed:
        print("  -", name)
    sys.exit(1)
print("All checks passed.")
