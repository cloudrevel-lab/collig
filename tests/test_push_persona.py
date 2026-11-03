#!/usr/bin/env python3
"""Tests for the local half of the persona publishing workflow."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

from push_persona import PublishError, assess_persona, copy_persona  # noqa: E402


def make_persona(root: Path, slug: str = "push-test", dossier: str = "# Push Test\n\nBody.\n") -> Path:
    persona = root / slug
    persona.mkdir(parents=True)
    (persona / "meta.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "name": "Push Test",
                "display_name": "Push Test",
                "canonical_name": "Push Test",
                "description": "Test.",
                "updated_at": "2026-01-01T00:00:00",
                "sources": [],
            }
        ),
        encoding="utf-8",
    )
    (persona / "PERSONALITY.md").write_text(dossier, encoding="utf-8")
    (persona / "sources.md").write_text("# Sources\n", encoding="utf-8")
    return persona


class PushPersonaTests(unittest.TestCase):
    def test_valid_persona_is_assessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            persona = make_persona(Path(tmp))
            result = assess_persona(persona)
            self.assertEqual(result["slug"], "push-test")
            self.assertEqual(result["name"], "Push Test")
            self.assertIn("PERSONALITY.md", result["files"])

    def test_secret_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            persona = make_persona(Path(tmp), dossier="# Push Test\n\nsk-" + "a" * 32 + "\n")
            with self.assertRaises(PublishError) as caught:
                assess_persona(persona)
            self.assertIn("openai-key", str(caught.exception).lower())

    def test_slug_must_match_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            persona = make_persona(Path(tmp))
            meta = json.loads((persona / "meta.json").read_text())
            meta["slug"] = "other"
            (persona / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
            with self.assertRaises(PublishError) as caught:
                assess_persona(persona)
            self.assertIn("slug", str(caught.exception).lower())

    def test_unexpected_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            persona = make_persona(Path(tmp))
            (persona / "run.sh").write_text("echo bad", encoding="utf-8")
            with self.assertRaises(PublishError):
                assess_persona(persona)

    def test_copy_persona(self):
        with tempfile.TemporaryDirectory() as tmp:
            persona = make_persona(Path(tmp) / "src")
            repo = Path(tmp) / "repo"
            (repo / "personas").mkdir(parents=True)
            target = copy_persona(persona, repo)
            self.assertTrue((target / "PERSONALITY.md").is_file())
            self.assertTrue((target / "meta.json").is_file())


if __name__ == "__main__":
    unittest.main()
