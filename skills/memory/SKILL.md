---
name: Memory & Notes
description: Save, search, and manage notes and memories
version: 1.1.0
author: Collig Team
license: MIT

tools:
  - name: add_note
    description: Add a new note to memory (plain text; passwords allowed with a warning)
  - name: list_notes
    description: List recent notes
  - name: search_notes
    description: Search notes by keyword
  - name: delete_notes
    description: Delete notes by their IDs

triggers:
  - note
  - remember
  - save note
  - my notes
  - search notes
  - memory
---

# Memory & Notes Skill

Provides note-taking and memory management capabilities.

Notes are stored in `~/.collig/data/memory_notes/notes.json` as plain text, so
saving never depends on an embedding provider, API key or quota.  Search is
lexical (keyword/substring) over that file.

Notes are saved exactly as written.  Passwords, tokens and other secrets are
allowed: the user gets a warning that the note is plain text, but the save is
never refused or blocked.

The old Chroma collection (`user_memory`) is imported into `notes.json` once,
on the first start after upgrading, so existing notes are preserved.
