#!/usr/bin/env python3
"""
Tests for the interactive "/" command menu.

The menu is only useful if selecting an entry actually completes it and lets
the leading slash command run.  These tests cover the completion helper behind
the Tab / Space / Enter key bindings.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)

from prompt_toolkit.buffer import Buffer, CompletionState
from prompt_toolkit.completion import CompleteEvent, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.keys import Keys

from core.cli import (
    SkillCommandCompleter,
    _argument_position,
    _at_parameter_boundary,
    _has_highlighted_completion,
    accept_completion,
    make_bottom_toolbar,
    make_prompt_key_bindings,
)
from core.personality import reset_personality_manager
from core.user_memory import reset_user_memory

passed = []
failed = []


def check(name, cond, detail=""):
    if cond:
        passed.append(name)
        print("PASS: " + name + ((" - " + detail) if detail else ""))
    else:
        failed.append(name)
        print("FAIL: " + name + ((" - " + detail) if detail else ""))


class _Agent:
    """Minimal stand-in for AgentService (only `.tools` is used)."""

    class _Tool:
        def __init__(self, name, description):
            self.name = name
            self.description = description

    tools = [_Tool("get_current_time", "Current time"), _Tool("search_news", "Search the news")]


def _document(text):
    return Document(text, len(text))


def _buffer(text, completions=None, index=None, with_completer=False):
    buffer = Buffer(document=_document(text))
    if with_completer:
        buffer.completer = SkillCommandCompleter(_Agent())
    if completions is not None:
        buffer.complete_state = CompletionState(
            original_document=_document(text),
            completions=completions,
            complete_index=index,
        )
    return buffer


def _completions(text):
    return list(SkillCommandCompleter(_Agent()).get_completions(_document(text), CompleteEvent()))


# ---------------------------------------------------------------------------
# 1. The completer lists slash commands and skill tools.
# ---------------------------------------------------------------------------
commands = _completions("/")
texts = [c.text for c in commands]
check("typing / lists commands", "config" in texts and "jira" in texts, "count=%d" % len(texts))
check("typing / lists skill tools", "get_current_time" in texts)

con = _completions("/con")
con_texts = [c.text for c in con]
check(
    "typing /con puts config first and filters the rest",
    con_texts[0] == "config" and "console" in con_texts,
    repr(con_texts),
)

# ---------------------------------------------------------------------------
# 2. accept_completion applies the highlighted entry, else the first.
# ---------------------------------------------------------------------------
buffer = _buffer("/con", completions=[Completion("config", start_position=-3)])
applied = accept_completion(buffer)
check("accept applies the first completion when none is highlighted", applied and buffer.text == "/config", buffer.text)

completions = [
    Completion("config", start_position=-2),
    Completion("console", start_position=-2),
]
buffer = _buffer("/co", completions=completions, index=1)
accept_completion(buffer)
check("accept respects the highlighted entry", buffer.text == "/console", buffer.text)

# ---------------------------------------------------------------------------
# 3. Space adds the separator needed for a parameter; Tab does not.
# ---------------------------------------------------------------------------
buffer = _buffer("/jir", completions=[Completion("jira", start_position=-3)])
accept_completion(buffer, append_space=True)
check("space accept appends a space", buffer.text == "/jira ", repr(buffer.text))

buffer = _buffer("/jir", completions=[Completion("jira", start_position=-3)])
accept_completion(buffer, append_space=False)
check("tab accept does not append a space", buffer.text == "/jira", repr(buffer.text))

# ---------------------------------------------------------------------------
# 4. Tab can complete even before prompt_toolkit has populated the menu.
# ---------------------------------------------------------------------------
buffer = _buffer("/con", with_completer=True)
applied = accept_completion(buffer)
check("accept computes completions when the menu is not populated", applied and buffer.text == "/config", buffer.text)

buffer = _buffer("hello", with_completer=True)
applied = accept_completion(buffer)
check("accept does nothing for plain chat text", not applied and buffer.text == "hello", repr(buffer.text))

# ---------------------------------------------------------------------------
# 5. Enter / second Space must treat trailing whitespace as the parameter.
# ---------------------------------------------------------------------------
check("no trailing space is not a parameter boundary", not _at_parameter_boundary("/jira"))
check("trailing space is a parameter boundary", _at_parameter_boundary("/jira "))
check("trailing tab is a parameter boundary", _at_parameter_boundary("/jira\t"))
check("typed parameter text is not a boundary", not _at_parameter_boundary("/jira get AIE-1"))

# ---------------------------------------------------------------------------
# 6. The prompt binds the documented keys.
# ---------------------------------------------------------------------------
bound_keys = {binding.keys for binding in make_prompt_key_bindings().bindings}
check("Tab is bound to completion", (Keys.ControlI,) in bound_keys)
check("Space is bound to completion", (" ",) in bound_keys)
check("Enter is bound to run", (Keys.ControlM,) in bound_keys)
check(
    "Ctrl+P / Ctrl+N remain history",
    (Keys.ControlP,) in bound_keys and (Keys.ControlN,) in bound_keys,
)
closed_toolbar = "".join(fragment[1] for fragment in make_bottom_toolbar()())
check(
    "closed toolbar advertises / commands and history",
    "Commands" in closed_toolbar and "History" in closed_toolbar,
    repr(closed_toolbar),
)

# ---------------------------------------------------------------------------
# 7. Dynamic argument completion: /chatto <person>, /distill show <name>, ...
# ---------------------------------------------------------------------------
_mgr = reset_personality_manager(
    tempfile.mkdtemp(prefix="collig-completion-personalities-"),
    complete=lambda *a, **k: "# Person\n\n## Who they are\nSomeone.\n",
    search=lambda *a, **k: [],
)
_mgr.distill("Anthony Albanese")
_mgr.distill("Ada Lovelace")

chatto_completions = _completions("/chatto ")
chatto_texts = [c.text for c in chatto_completions]
check(
    "typing /chatto with a space lists personalities",
    "Anthony Albanese" in chatto_texts and "Ada Lovelace" in chatto_texts,
    repr(chatto_texts),
)
check("chatto also lists off/list actions", "off" in chatto_texts and "list" in chatto_texts)
check(
    "personality names come before the actions",
    chatto_texts.index("Anthony Albanese") < chatto_texts.index("off"),
    repr(chatto_texts),
)
filtered = [c.text for c in _completions("/chatto ant")]
check("chatto filters personalities by prefix", filtered[:1] == ["Anthony Albanese"], repr(filtered))

buffer = _buffer("/chatto ant", with_completer=True)
accept_completion(buffer)
check(
    "accepting a personality replaces the typed argument",
    buffer.text == "/chatto Anthony Albanese",
    repr(buffer.text),
)

show_texts = [c.text for c in _completions("/distill show ")]
check("distill show lists personalities", "Anthony Albanese" in show_texts, repr(show_texts))
rm_texts = [c.text for c in _completions("/distill rm ")]
check("distill rm lists personalities", "Ada Lovelace" in rm_texts, repr(rm_texts))

_mem = reset_user_memory(tempfile.mkdtemp(prefix="collig-completion-memory-"), config_loader=lambda: {})
_mem.upsert_fact("home_location", "Sydney", category="location", source="explicit")
forget_completions = list(_completions("/memory forget "))
check(
    "memory forget lists fact keys",
    "home_location" in [c.text for c in forget_completions],
    repr([c.text for c in forget_completions]),
)
check(
    "memory forget shows the remembered value",
    any("Sydney" in str(c.display_meta) for c in forget_completions),
)

check("/chatto with no space is still a command position", not _argument_position("/chatto"))
check("/chatto with a space is an argument position", _argument_position("/chatto "))
check("/personality with a space is an argument position", _argument_position("/personality "))
check("/distill show with a space is an argument position", _argument_position("/distill show "))
check("/distill with a space is still a command position", not _argument_position("/distill "))
check("/jira with a space is not a name argument", not _argument_position("/jira "))

# Space picks the highlighted name at an argument position.
_space = next(b for b in make_prompt_key_bindings().bindings if b.keys == (" ",))
buffer = _buffer(
    "/chatto ",
    completions=[Completion("Anthony Albanese", start_position=0)],
    index=0,
)
_space.handler(SimpleNamespace(current_buffer=buffer))
check(
    "Space selects the highlighted personality",
    buffer.text == "/chatto Anthony Albanese",
    repr(buffer.text),
)

# ... but stays literal at a sub-command position like /jira .
buffer = _buffer(
    "/jira ",
    completions=[Completion("jira sprint", start_position=-5)],
    index=0,
)
_space.handler(SimpleNamespace(current_buffer=buffer))
check("Space stays literal for sub-commands", buffer.text == "/jira  ", repr(buffer.text))

_tab = next(b for b in make_prompt_key_bindings().bindings if b.keys == (Keys.ControlI,))
buffer = _buffer(
    "/chatto ",
    completions=[Completion("Ada Lovelace", start_position=0)],
    index=0,
)
_tab.handler(SimpleNamespace(current_buffer=buffer))
check("Tab selects the highlighted personality", buffer.text == "/chatto Ada Lovelace", repr(buffer.text))

buffer = _buffer(
    "/chatto ",
    completions=[Completion("Ada Lovelace", start_position=0)],
    index=0,
)
check("an arrow selection is detected", _has_highlighted_completion(buffer))
buffer = _buffer(
    "/chatto ",
    completions=[Completion("Ada Lovelace", start_position=0)],
    index=None,
)
check("the menu with no explicit selection is not highlighted", not _has_highlighted_completion(buffer))

# ---------------------------------------------------------------------------
# 8. Same-name personalities are shown with their canonical context
# ---------------------------------------------------------------------------
_AMBIGUOUS = {
    "ambiguous": True,
    "candidates": [
        {
            "display_name": "大宋佳",
            "canonical_name": "宋佳",
            "aliases": ["宋佳", "大宋佳"],
            "description": "80年代百花影后",
            "key_facts": [],
            "source_urls": [],
            "confidence": 0.9,
        },
        {
            "display_name": "小宋佳",
            "canonical_name": "宋佳",
            "aliases": ["宋佳", "小宋佳"],
            "description": "《闯关东》《人世间》演员",
            "key_facts": [],
            "source_urls": [],
            "confidence": 0.95,
        },
    ],
}


def _ambiguous_complete(messages, **kwargs):
    if "Identify the distinct public people" in messages[-1]["content"]:
        return json.dumps(_AMBIGUOUS, ensure_ascii=False)
    return "# Person\n\n## Who they are\nSomeone.\n"


_mgr = reset_personality_manager(
    tempfile.mkdtemp(prefix="collig-completion-ambiguous-"),
    complete=_ambiguous_complete,
    search=lambda query, n=4: [],
)
_mgr.distill("宋佳", pick=2)
_mgr.distill("宋佳", pick=1)
_chatto_completions = _completions("/chatto ")
_chatto_names = [c.text for c in _chatto_completions]
check(
    "completion shows both same-name people",
    "大宋佳" in _chatto_names and "小宋佳" in _chatto_names,
    repr(_chatto_names),
)
_chatto_meta = {c.text: str(c.display_meta) for c in _chatto_completions}
check(
    "completion meta shows the shared canonical name",
    "宋佳" in _chatto_meta.get("小宋佳", "") and "宋佳" in _chatto_meta.get("大宋佳", ""),
    repr(_chatto_meta),
)
check(
    "typing the display prefix selects one person",
    [c.text for c in _completions("/chatto 小")] == ["小宋佳"],
    repr([c.text for c in _completions("/chatto 小")]),
)

# ---------------------------------------------------------------------------
print("\n================ SUMMARY ================")
print("%d passed, %d failed" % (len(passed), len(failed)))
if failed:
    for name in failed:
        print("  -", name)
    sys.exit(1)
print("All checks passed.")
