---
name: Memory & Notes
description: Save, search, and manage notes and memories
version: 1.0.0
author: Collig Team
license: MIT

tools:
  - name: add_note
    description: Add a new note to memory
  - name: list_notes
    description: List recent notes
  - name: search_notes
    description: Search notes by semantic similarity
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

Provides note-taking and memory management capabilities using vector embeddings for semantic search.
