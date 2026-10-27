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
print("\n================ SUMMARY ================")
print("%d passed, %d failed" % (len(passed), len(failed)))
if failed:
    for name in failed:
        print("  -", name)
    sys.exit(1)
print("All checks passed.")
