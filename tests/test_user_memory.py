#!/usr/bin/env python3
"""Tests for the persistent user-memory store (no network, no real home dir)."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)

from core.user_memory import (  # noqa: E402
    UserMemoryStore,
    extract_heuristics,
    extract_weather_location,
    normalize_key,
    time_bucket,
    reset_user_memory,
)

passed = []
failed = []


def check(name, cond, detail=""):
    if cond:
        passed.append(name)
        print("PASS: " + name + ((" - " + detail) if detail else ""))
    else:
        failed.append(name)
        print("FAIL: " + name + ((" - " + detail) if detail else ""))


def new_store(config=None):
    root = tempfile.mkdtemp(prefix="collig-memory-test-")
    return UserMemoryStore(root, config_loader=lambda: dict(config or {}))


# ---------------------------------------------------------------------------
# Extraction heuristics
# ---------------------------------------------------------------------------
facts = {fact["key"]: fact for fact in extract_heuristics("I live in Sydney and my name is Jacob")}
check(
    "heuristics find a location",
    facts.get("home_location", {}).get("value") == "Sydney",
    repr(facts.get("home_location")),
)
check("heuristics find a name", facts.get("name", {}).get("value") == "Jacob")
check(
    "explicit location has high confidence",
    facts.get("home_location", {}).get("confidence", 0) >= 0.9,
)
family = extract_heuristics("my daughter will have a party on Saturday")
check("family detail is captured", any(f["key"] == "family_daughter" for f in family), repr(family))
check(
    "family detail is stored without the possessive prefix",
    all(not f["value"].lower().startswith("my ") for f in family),
    repr(family),
)
check(
    "lowercase fallback does not create a note duplicate",
    len(extract_heuristics("Remember that I prefer morning meetings")) == 1,
    repr(extract_heuristics("Remember that I prefer morning meetings")),
)
check("weather city is parsed", extract_weather_location("what's the weather in Sydney tomorrow?") == "Sydney")
check("multi-word weather city is parsed", extract_weather_location("forecast for New York this week") == "New York")
check("weather time hint is not a city", extract_weather_location("weather for tomorrow") is None)
check(
    "secret-looking values are rejected",
    extract_heuristics("my password is hunter2") == [],
    repr(extract_heuristics("my password is hunter2")),
)
check(
    "a direct location answer is captured",
    next(
        (f["value"] for f in extract_heuristics("the location is oatlands nsw 2117") if f["key"] == "home_location"),
        None,
    )
    == "Oatlands NSW 2117",
)
check(
    "a possessive location answer is explicit",
    any(
        f["key"] == "home_location" and f["source"] == "explicit"
        for f in extract_heuristics("my location is oatlands nsw 2117")
    ),
)
check(
    "street address is kept verbatim",
    next(
        (f["value"] for f in extract_heuristics("I live at 12 Main Street, Sydney") if f["key"] == "home_address"),
        None,
    )
    == "12 Main Street, Sydney",
)
check(
    "preferences about the assistant are ignored",
    extract_heuristics("I like your style") == [],
    repr(extract_heuristics("I like your style")),
)
check(
    "concrete preferences are captured",
    any(f["category"] == "preference" for f in extract_heuristics("I love flat white coffee")),
)
check(
    "call me when is not a name",
    extract_heuristics("call me when you're done") == [],
    repr(extract_heuristics("call me when you're done")),
)
check("capitalised call me is a name", any(f["key"] == "name" for f in extract_heuristics("call me Jacob")))
check(
    "figurative location is rejected",
    extract_heuristics("I live in the moment") == [],
    repr(extract_heuristics("I live in the moment")),
)
check(
    "time buckets cover the day",
    (
        time_bucket(datetime(2026, 1, 1, 8)) == "morning"
        and time_bucket(datetime(2026, 1, 1, 14)) == "afternoon"
        and time_bucket(datetime(2026, 1, 1, 20)) == "evening"
    ),
)
check("key normalization is stable", normalize_key("Home Location!") == "home_location")

# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------
store = new_store()
fact = store.upsert_fact(
    "home_location", "Sydney", category="location", confidence=0.9, source="explicit", evidence="I live in Sydney"
)
check("upsert returns a fact", fact is not None and fact["key"] == "home_location")
check("fact is persisted", store.get_fact("home_location")["value"] == "Sydney")
again = store.upsert_fact("home_location", "Sydney", category="location", confidence=0.9, source="explicit")
check(
    "same value increments mentions, not duplicates",
    again["mentions"] == 2 and len(store.list_facts()) == 1,
    repr(again),
)
store.upsert_fact("home_location", "Melbourne", category="location", confidence=0.5, source="inferred")
check("inferred value does not overwrite an explicit fact", store.get_fact("home_location")["value"] == "Sydney")
store.upsert_fact("home_location", "Melbourne", category="location", confidence=0.95, source="explicit")
check("explicit correction wins", store.get_fact("home_location")["value"] == "Melbourne")
check("correction keeps a short history", store.get_fact("home_location").get("history", [])[-1]["value"] == "Sydney")
store.upsert_fact("family_daughter", "will have a party", category="family", confidence=0.8, source="inferred")
store.upsert_fact("family_daughter", "is called Mia", category="family", confidence=0.85, source="explicit")
daughter = store.get_fact("family_daughter")
check(
    "family details merge instead of replacing",
    "party" in daughter["value"] and "Mia" in daughter["value"],
    daughter["value"],
)
check("forget removes one fact", store.forget("family_daughter") and store.get_fact("family_daughter") is None)
check("forget reports unknown keys", store.forget("family_daughter") is False)
check("search finds a fact", any(f["key"] == "home_location" for f in store.search("where do I live")))
check("summary lists keys", "home_location" in store.summary())

# ---------------------------------------------------------------------------
# Repeated weather locations become the home city
# ---------------------------------------------------------------------------
store = new_store()
store.observe_message("what's the weather in Sydney?")
check("one weather mention is not enough for home", store.get_fact("home_location") is None)
store.observe_message("and the weather in Sydney tomorrow?")
home = store.get_fact("home_location")
check(
    "repeated weather city becomes home_location",
    home is not None and home["value"] == "Sydney" and home["source"] == "behavior",
    repr(home),
)
check("inferred home confidence stays moderate", 0.5 <= home["confidence"] <= 0.85, str(home["confidence"]))
check("USER.md is rendered", os.path.exists(store.markdown_path) and "Sydney" in store.markdown_path.read_text())
check("events are audited", os.path.exists(store.events_path) and "fact.add" in store.events_path.read_text())

# ---------------------------------------------------------------------------
# Prompt block
# ---------------------------------------------------------------------------
store = new_store()
check("empty store produces no prompt block", store.prompt_block() == "")
store.observe_message("I live in Sydney. My name is Jacob.")
block = store.prompt_block()
check("prompt block includes location", "Sydney" in block)
check("prompt block includes name", "Jacob" in block)
check("prompt block marks explicit facts", "explicit" in block)
check("prompt block forbids reciting the list", "Do not recite" in block)
check("prompt block is bounded", len(block) <= 2200, str(len(block)))
store.clear()
check("clear removes facts", store.list_facts() == [] and store.prompt_block() == "")

# ---------------------------------------------------------------------------
# Interests, routines and proactive gating
# ---------------------------------------------------------------------------
store = new_store({"USER_MEMORY_PROACTIVE": True})
for index in range(3):
    store.record_skill_usage(["News Search"], now=datetime(2026, 10, 26 + index, 8, 0, 0))
check("repeated tool use becomes a habit", store.due_routine(now=datetime(2026, 10, 29, 8, 30, 0)) is not None)
check("repeated tool use records an interest", "news" in store._load_state().get("interests", {}))
check("habit is not due in the wrong bucket", store.due_routine(now=datetime(2026, 10, 29, 14, 0, 0)) is None)
store.mark_proactive("news", now=datetime(2026, 10, 29, 8, 30, 0))
check("a routine fires once per bucket/day", store.due_routine(now=datetime(2026, 10, 29, 9, 0, 0)) is None)
check("the next day is due again", store.due_routine(now=datetime(2026, 10, 30, 8, 30, 0)) is not None)
off = new_store({"USER_MEMORY_PROACTIVE": False})
for index in range(3):
    off.record_skill_usage(["News Search"], now=datetime(2026, 10, 26 + index, 8, 0, 0))
check("proactive can be disabled", off.due_routine(now=datetime(2026, 10, 29, 8, 30, 0)) is None)

explicit = new_store({"USER_MEMORY_PROACTIVE": True})
explicit.observe_message("I usually check AI news in the morning", now=datetime(2026, 10, 28, 8, 0, 0))
check("explicit routine is captured", "news" in explicit._load_state().get("habits", {}))
check(
    "explicit routine respects its bucket",
    explicit.due_routine(now=datetime(2026, 10, 29, 9, 0, 0)) is not None
    and explicit.due_routine(now=datetime(2026, 10, 29, 15, 0, 0)) is None,
)

# ---------------------------------------------------------------------------
# Proactive routing (greeting -> due routine's tool)
# ---------------------------------------------------------------------------
proactive = reset_user_memory(
    tempfile.mkdtemp(prefix="collig-memory-proactive-"),
    config_loader=lambda: {"USER_MEMORY_PROACTIVE": True},
)
proactive.add_habit(
    "news",
    "check AI news",
    time_of_day="any",
    confidence=0.9,
    source="explicit",
    now=datetime.now() - timedelta(days=2),
)

import asyncio  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from google.genai import types as genai_types  # noqa: E402

from agents.collig.toolsets import SkillToolset  # noqa: E402


class _TurnContext:
    def __init__(self, text):
        self.user_content = genai_types.Content(role="user", parts=[genai_types.Part(text=text)])
        self.session = SimpleNamespace(events=[], id="test-session")


_toolset = SkillToolset()
_greeting_names = [t.name for t in asyncio.run(_toolset.get_tools(_TurnContext("hello")))]
check(
    "due routine is not offered on math",
    "search_news" not in [t.name for t in asyncio.run(_toolset.get_tools(_TurnContext("2+2")))],
)
# The greeting should get the news tool even though "hello" routes to no skill.
check("greeting offers the due routine's tool", "search_news" in _greeting_names, repr(_greeting_names))
check(
    "a scheduling message is not treated as a greeting",
    "search_news" not in [t.name for t in asyncio.run(_toolset.get_tools(_TurnContext("morning meeting notes")))],
)

# ---------------------------------------------------------------------------
# Disabled memory
# ---------------------------------------------------------------------------
disabled = new_store({"USER_MEMORY_ENABLED": False})
disabled.observe_message("I live in Sydney")
dis = disabled.upsert_fact("home_location", "Sydney", category="location", source="explicit")
check("explicit tool writes still work when capture is off", dis is not None)
check("prompt block is empty when disabled", disabled.prompt_block() == "")
check("disabled store captures no turns", disabled._load_state()["stats"]["turns_seen"] == 0)

# ---------------------------------------------------------------------------
# LLM extraction payload
# ---------------------------------------------------------------------------
store = new_store()
store._complete = lambda messages, **kwargs: (
    '{"facts":[{"key":"dog_name","value":"Rex","category":"family",'
    '"confidence":0.9,"evidence":"my dog Rex"}],'
    '"interests":["dogs"],'
    '"habits":[{"intent":"news","label":"checks AI news","time_of_day":"morning",'
    '"confidence":0.8}]}'
)
store._llm_extract("My dog Rex keeps barking", "", [])
check("LLM extraction stores facts", store.get_fact("dog_name") is not None)
check("LLM extraction stores interests", "dogs" in store._load_state().get("interests", {}))
check("LLM extraction stores habits", "news" in store._load_state().get("habits", {}))
bad = new_store()
bad._complete = lambda messages, **kwargs: "not json at all"
bad._llm_extract("My dog Rex keeps barking", "", [])
check("malformed LLM output is ignored", bad.list_facts() == [])

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print("\n================ SUMMARY ================")
print(f"{len(passed)} passed, {len(failed)} failed")
if failed:
    print("Failures: " + ", ".join(failed))
    sys.exit(1)
print("All checks passed.")
