---
name: Bookmarks
description: Save, search, and manage bookmarks
version: 1.0.0
author: Collig Team
license: MIT

tools:
  - name: add_bookmark
    description: Save a bookmark
  - name: list_bookmarks
    description: List saved bookmarks
  - name: search_bookmarks
    description: Search bookmarks by semantic similarity
  - name: delete_bookmark
    description: Delete a bookmark by URL
  - name: open_bookmark
    description: Open a bookmark in the browser

triggers:
  - bookmark
  - save link
  - saved links
  - favorites
---

# Bookmarks Skill

Allows saving and retrieving bookmarks using vector embeddings for semantic search.
