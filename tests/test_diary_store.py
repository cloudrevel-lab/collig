#!/usr/bin/env python3
"""Tests for the JSON-backed diary store and skill."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)

from skills.diary import DiarySkill  # noqa: E402
from skills.diary.store import DiaryStore  # noqa: E402


class DiaryStoreTests(unittest.TestCase):
    def test_crud_and_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DiaryStore(Path(tmp) / "diary.json")
            one = store.add("Booked a room for two nights", date="2026-11-13")
            two = store.add("Walked by the harbour", date="2026-11-14")
            self.assertEqual({item["id"] for item in store.list()}, {one["id"], two["id"]})
            self.assertEqual(store.get(one["id"])["content"], "Booked a room for two nights")
            self.assertEqual(store.list(start_date="2026-11-14")[0]["id"], two["id"])
            self.assertEqual(store.search("harbour")[0]["id"], two["id"])
            updated = store.update(one["id"], "Booked a room for three nights")
            self.assertEqual(updated["content"], "Booked a room for three nights")
            self.assertEqual(store.delete([one["id"]]), 1)
            self.assertIsNone(store.get(one["id"]))

    def test_empty_content_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DiaryStore(Path(tmp) / "diary.json")
            with self.assertRaises(ValueError):
                store.add("   ")

    def test_legacy_import_is_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DiaryStore(Path(tmp) / "diary.json")
            entries = [
                {"id": "a", "content": "old entry", "date": "2026-01-01", "timestamp": "2026-01-01T10:00:00"},
                {"id": "b", "content": "old entry", "date": "2026-01-01", "timestamp": "2026-01-01T10:00:00"},
            ]
            self.assertEqual(store.import_entries(entries), 1)
            self.assertEqual(store.import_entries(entries), 0)
            self.assertTrue(store.legacy_imported())

    def test_skill_uses_injected_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "diary.json"
            skill = DiarySkill(entry_store_path=str(path))
            skill.configure({})
            saved = skill.store_entry("A skill-level entry", date="2026-11-04")
            self.assertTrue(path.is_file())
            self.assertEqual(skill.get_entry(saved["id"])["content"], "A skill-level entry")
            self.assertEqual(skill.list_entries(start_date="2026-11-04")[0]["id"], saved["id"])
            self.assertEqual(skill.remove_entries([saved["id"]]), 1)


if __name__ == "__main__":
    unittest.main()
