#!/usr/bin/env python3
"""Offline tests for the persona market client."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)

import core.persona_market as persona_market_module  # noqa: E402
from core.commands import handle_slash_command  # noqa: E402
from core.persona_market import MarketError, PersonaMarket  # noqa: E402

REPO = "test/repo"
REF = "main"
BASE = f"https://raw.githubusercontent.com/{REPO}/{REF}"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _fixture(tmp: Path, *, slug: str = "market-test", dossier: bytes | None = None):
    raw_meta = {
        "slug": slug,
        "name": "Market Test",
        "display_name": "Market Test",
        "canonical_name": "Market Test",
        "description": "A persona used by the market tests.",
        "updated_at": "2026-01-01T00:00:00",
        "aliases": ["Tester"],
        "sources": [{"title": "Example", "url": "https://example.com"}],
    }
    meta = json.dumps(raw_meta, ensure_ascii=False, indent=2).encode()
    dossier = dossier if dossier is not None else b"# Market Test\n\nA test dossier.\n"
    sources = b"# Sources\n\n- https://example.com\n"
    files = {
        "meta.json": meta,
        "PERSONALITY.md": dossier,
        "sources.md": sources,
    }
    entry = {
        "slug": slug,
        "name": "Market Test",
        "display_name": "Market Test",
        "canonical_name": "Market Test",
        "description": "A persona used by the market tests.",
        "aliases": ["Tester"],
        "updated_at": "2026-01-01T00:00:00",
        "source_count": 1,
        "files": {name: _sha(raw) for name, raw in files.items()},
    }
    index = {"schema": 1, "persona_count": 1, "personas": [entry]}
    urls = {
        f"{BASE}/index.json": json.dumps(index, ensure_ascii=False).encode(),
    }
    for name, raw in files.items():
        urls[f"{BASE}/personas/{slug}/{name}"] = raw
    return entry, urls


class FakeManager:
    def __init__(self):
        self.items = []

    def list(self):
        return self.items


class PersonaMarketTests(unittest.TestCase):
    def make_market(self, tmp: Path, urls, *, manager=None):
        return PersonaMarket(
            repo=REPO,
            ref=REF,
            root=tmp / "personalities",
            cache_path=tmp / "cache" / "index.json",
            fetch=lambda url: urls[url],
            manager=manager or FakeManager(),
        )

    def test_catalog_and_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            entry, urls = _fixture(tmp)
            market = self.make_market(tmp, urls)
            catalog = market.catalog()
            self.assertEqual(catalog["personas"][0]["slug"], "market-test")
            results = market.list_personas()
            self.assertEqual(results[0]["number"], 1)
            self.assertFalse(results[0]["installed"])

            result = market.install("market-test")
            self.assertTrue(result["ok"])
            self.assertTrue((tmp / "personalities" / "market-test" / "meta.json").is_file())
            self.assertEqual(
                (tmp / "personalities" / "market-test" / "PERSONALITY.md").read_bytes(),
                b"# Market Test\n\nA test dossier.\n",
            )
            with self.assertRaises(MarketError):
                market.install("market-test")
            self.assertTrue(market.install("market-test", force=True)["ok"])

    def test_number_selector_and_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            entry, urls = _fixture(tmp)
            market = self.make_market(tmp, urls)
            market.catalog()
            self.assertEqual(market.resolve("1")["slug"], "market-test")
            self.assertEqual(market.resolve("Tester")["slug"], "market-test")
            self.assertEqual(len(market.search("market")), 1)

    def test_checksum_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            entry, urls = _fixture(tmp)
            bad = dict(entry)
            bad["files"] = dict(entry["files"])
            bad["files"]["PERSONALITY.md"] = "0" * 64
            urls[f"{BASE}/index.json"] = json.dumps({"schema": 1, "personas": [bad]}).encode()
            market = self.make_market(tmp, urls)
            market.catalog()
            with self.assertRaises(MarketError) as caught:
                market.install("market-test")
            self.assertIn("checksum", str(caught.exception))

    def test_secret_material_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _entry, urls = _fixture(tmp, dossier=b"# Market Test\n\nsk-" + b"a" * 32 + b"\n")
            market = self.make_market(tmp, urls)
            market.catalog()
            with self.assertRaises(MarketError) as caught:
                market.install("market-test")
            self.assertIn("credential", str(caught.exception))

    def test_traversal_slug_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _entry, urls = _fixture(tmp, slug="../escape")
            market = self.make_market(tmp, urls)
            with self.assertRaises(MarketError):
                market.catalog()

    def test_cache_fallback_when_fetch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _entry, urls = _fixture(tmp)
            market = self.make_market(tmp, urls)
            market.catalog()
            broken = PersonaMarket(
                repo=REPO,
                ref=REF,
                root=tmp / "personalities",
                cache_path=tmp / "cache" / "index.json",
                fetch=lambda url: (_ for _ in ()).throw(RuntimeError("offline")),
                manager=FakeManager(),
            )
            catalog = broken.catalog(refresh=True)
            self.assertEqual(catalog["personas"][0]["slug"], "market-test")
            self.assertTrue(broken.used_cache)

    def test_load_personas_command_lists_and_installs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _entry, urls = _fixture(tmp)
            market = self.make_market(tmp, urls)
            old = persona_market_module._MARKET
            persona_market_module._MARKET = market
            try:
                listing = handle_slash_command("/load-personas")
                self.assertIn("1. Market Test", listing)
                result = handle_slash_command("/load-personas 1")
                self.assertIn("Installed Market Test", result)
                self.assertTrue((tmp / "personalities" / "market-test" / "PERSONALITY.md").is_file())
                again = handle_slash_command("/load-personas --all")
                self.assertIn("SKIP", again)
            finally:
                persona_market_module._MARKET = old

    def test_format_catalog_has_numbered_install_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _entry, urls = _fixture(tmp)
            market = self.make_market(tmp, urls)
            text = market.format_catalog()
            self.assertIn("1. Market Test", text)
            self.assertIn("/load-personas <number|name>", text)


if __name__ == "__main__":
    unittest.main()
