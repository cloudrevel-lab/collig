#!/usr/bin/env python3
"""Offline tests for local note storage and the Memory & Notes skill."""

from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)

from skills.memory import MemorySkill, note_warning  # noqa: E402
from skills.memory.store import NoteStore  # noqa: E402

passed = []
failed = []


def check(name, cond, detail=""):
    if cond:
        passed.append(name)
        print("PASS: " + name + ((" - " + detail) if detail else ""))
    else:
        failed.append(name)
        print("FAIL: " + name + ((" - " + detail) if detail else ""))


def tmp_store():
    folder = tempfile.mkdtemp(prefix="collig-notes-test-")
    return NoteStore(os.path.join(folder, "notes.json")), folder


# ---------------------------------------------------------------------------
# NoteStore basics
# ---------------------------------------------------------------------------
store, folder = tmp_store()
check("an empty store lists nothing", store.list() == [])

first = store.add("educhat: https://chat-preprod.education.nsw.gov.au/")
second = store.add("buy milk")
check("add returns an id", bool(first.get("id")))
check("list is newest first", [n["id"] for n in store.list()] == [second["id"], first["id"]])

reopened = NoteStore(store.path)
check("notes survive a reopen", len(reopened.list()) == 2, str(reopened.list()))
check("file exists on disk", os.path.exists(store.path))

found = reopened.search("educhat")
check("search finds a note", len(found) == 1 and found[0]["id"] == first["id"])
check("search is case-insensitive", len(reopened.search("EDUCHAT")) == 1)
check("search by several words", len(reopened.search("buy milk")) == 1)
check("search misses cleanly", reopened.search("nothing here") == [])

updated = reopened.update(first["id"], "educhat: new url")
check("update changes content", updated and updated["content"] == "educhat: new url")
check("update unknown id returns None", reopened.update("missing", "x") is None)

removed = reopened.delete([second["id"], "missing"])
check("delete reports only removed notes", removed == 1)
check("deleted note is gone", reopened.search("milk") == [])

# Empty notes are rejected, never silently stored.
try:
    reopened.add("   ")
    check("blank note is rejected", False)
except ValueError:
    check("blank note is rejected", True)

# ---------------------------------------------------------------------------
# Legacy import
# ---------------------------------------------------------------------------
legacy, _ = tmp_store()
legacy.add("kept once")
entries = [
    {"content": "older note", "timestamp": "2024-01-01T00:00:00"},
    {"content": "older note", "timestamp": "2024-01-01T00:00:00"},
    {"content": "second older note", "timestamp": "2024-01-02T00:00:00"},
]
added = legacy.import_notes(entries)
check("legacy import adds only new notes", added == 2, str(legacy.list()))
check("legacy import is marked done", legacy.legacy_imported())
check("legacy import is idempotent", legacy.import_notes(entries) == 0)

# ---------------------------------------------------------------------------
# Skill: notes are plain text and passwords never block a save
# ---------------------------------------------------------------------------
skill_dir = tempfile.mkdtemp(prefix="collig-memory-skill-test-")
skill = MemorySkill(note_store_path=os.path.join(skill_dir, "notes.json"))
skill.configure({})

secret_note = "educhat https://chat-preprod.education.nsw.gov.au/ username: a@b.c password: hunter2"
result = skill.store_note(secret_note)
check("a password note is saved", result["note"]["content"] == secret_note)
check("a password note produces a warning", "plain text" in result["warning"].lower())
check("password note is in recent_notes", skill.recent_notes()[0]["content"] == secret_note)
check("note_warning is quiet for normal text", note_warning("buy milk") == "")

tools = {tool.name: tool for tool in skill.get_tools()}
add_tool = tools["add_note"]
reply = add_tool.invoke({"content": "api key: FAKE_TEST_VALUE"})
check("the add_note tool succeeds for a secret", reply.startswith("Note saved successfully."), reply)
check("the add_note tool warns about plain text", "plain text" in reply.lower(), reply)
check("the note tool result is searchable", "FAKE_TEST_VALUE" in (skill.recent_notes()[0]["content"]))

listed = tools["list_notes"].invoke({"limit": 5})
check("list_notes shows saved notes", "FAKE_TEST_VALUE" in listed, listed)
searched = tools["search_notes"].invoke({"query": "educhat"})
check("search_notes finds the saved note", "educhat" in searched, searched)

count = len(skill.recent_notes())
deleted = tools["delete_notes"].invoke({"note_ids": [skill.recent_notes()[0]["id"]]})
check("delete_notes reports a deletion", deleted.startswith("Deleted 1"), deleted)
check("delete_notes really removed it", len(skill.recent_notes()) == count - 1)

# ---------------------------------------------------------------------------
# Explicit /memory note saves may contain secrets; inferred facts may not
# ---------------------------------------------------------------------------
from core.user_memory import UserMemoryStore, extract_heuristics, looks_sensitive  # noqa: E402

um_root = tempfile.mkdtemp(prefix="collig-um-test-")
um = UserMemoryStore(um_root, config_loader=lambda: {})
check("looks_sensitive spots a password", looks_sensitive("password: hunter2"))
check("looks_sensitive ignores ordinary text", not looks_sensitive("buy milk"))

check(
    "inferred facts still reject secrets",
    um.upsert_fact("note_x", "password: hunter2", source="explicit") is None,
)
allowed = um.upsert_fact(
    "note_secret", "password: hunter2", source="explicit", allow_sensitive=True
)
check("explicit notes may store secrets", allowed is not None and allowed["value"] == "password: hunter2")

check(
    "auto-extraction still drops passwords",
    extract_heuristics("my password is hunter2") == [],
    repr(extract_heuristics("my password is hunter2")),
)

# ---------------------------------------------------------------------------
print()
print(f"{len(passed)} passed, {len(failed)} failed")
if failed:
    print("Failed: " + ", ".join(failed))
    sys.exit(1)
