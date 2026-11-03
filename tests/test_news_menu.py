#!/usr/bin/env python3
"""Regression tests for the interactive news browser.

The browser used to write to the Rich console from inside a running
prompt_toolkit application, and it used to close/reopen the application after
an action.  Both made the screen drift, duplicate rows and open links twice.
These tests drive the menu through prompt_toolkit's in-memory input so they
run headless.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)

import webbrowser  # noqa: E402

from prompt_toolkit.application import create_app_session  # noqa: E402
from prompt_toolkit.input import create_pipe_input  # noqa: E402
from prompt_toolkit.output import DummyOutput  # noqa: E402

import core.news_cache as news_cache_mod  # noqa: E402
from core.cli import browse_news_items  # noqa: E402
from core.paths import paths  # noqa: E402

# Belt and braces: even if a test forgets to substitute the cache manager, it
# must never write into the real ~/.collig data directory.
_TMP_HOME = tempfile.mkdtemp(prefix="collig-news-test-")
paths.home = _TMP_HOME
paths.data_dir = os.path.join(_TMP_HOME, "data")
paths.storage_dir = os.path.join(_TMP_HOME, "storage")
news_cache_mod._news_cache_manager = None

passed = []
failed = []


def check(name, cond, detail=""):
    if cond:
        passed.append(name)
        print("PASS: " + name + ((" - " + detail) if detail else ""))
    else:
        failed.append(name)
        print("FAIL: " + name + ((" - " + detail) if detail else ""))


ITEMS = [
    {
        "title": "Test headline %d" % i,
        "source": "Test Source",
        "date": "2026-10-02T16:14:00+00:00",
        "body": "Body %d" % i,
        "url": "https://example.com/%d" % i,
    }
    for i in range(1, 11)
]


class FakeCacheManager:
    def __init__(self):
        self.saved = []

    def save_search(self, query, news_items, session_id=None):
        self.saved.append((query, news_items))
        return "news_%06d" % (len(self.saved) + 1)


def run_browser(keys, items=None, query="test query"):
    """Run the browser with piped key presses; return (stdout, results)."""
    items = ITEMS if items is None else items
    fake_cache = FakeCacheManager()
    opened = []

    original_get_cache = news_cache_mod.get_news_cache_manager
    original_open = webbrowser.open
    news_cache_mod.get_news_cache_manager = lambda: fake_cache
    webbrowser.open = lambda url, *a, **kw: opened.append(url) or True

    captured = io.StringIO()
    try:
        with create_pipe_input() as pipe:
            pipe.send_text(keys)
            with create_app_session(input=pipe, output=DummyOutput()):
                with contextlib.redirect_stdout(captured):
                    browse_news_items(list(items), query, None)
    finally:
        news_cache_mod.get_news_cache_manager = original_get_cache
        webbrowser.open = original_open

    return captured.getvalue(), fake_cache, opened


# ---------------------------------------------------------------------------
# Opening an item must not print inside the app and must not open twice.
# ---------------------------------------------------------------------------
out, cache, opened = run_browser("jo" + "q")
check("open action opens the selected item once", opened == ["https://example.com/2"], repr(opened))
check("open action writes nothing to the console", out == "", repr(out))
check("open action does not save anything", cache.saved == [])

# ---------------------------------------------------------------------------
# Saving must render its feedback in-UI instead of printing over the layout.
# ---------------------------------------------------------------------------
out, cache, opened = run_browser("js" + "q")
check("save action saves the current search once", len(cache.saved) == 1)
check("save action saves the right query", cache.saved and cache.saved[0][0] == "test query")
check("save action saves the current items", cache.saved and cache.saved[0][1] == list(ITEMS))
check("save action writes nothing to the console", out == "", repr(out))
check("save action does not open anything", opened == [])

# ---------------------------------------------------------------------------
# Quitting is silent and leaves the terminal alone.
# ---------------------------------------------------------------------------
out, cache, opened = run_browser("q")
check("quit action writes nothing to the console", out == "", repr(out))
check("quit action does not save or open", cache.saved == [] and opened == [])

# ---------------------------------------------------------------------------
# An empty list must not start an application at all.
# ---------------------------------------------------------------------------
out, cache, opened = run_browser("q", items=[])
check("empty list warns instead of opening the browser", "No news items to browse" in out, repr(out))

# ---------------------------------------------------------------------------
print("\n================ SUMMARY ================")
print("%d passed, %d failed" % (len(passed), len(failed)))
if failed:
    for name in failed:
        print("  -", name)
    sys.exit(1)
print("All checks passed.")
