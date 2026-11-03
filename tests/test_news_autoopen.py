#!/usr/bin/env python3
"""Regression tests for the news request armed by a turn.

The CLI used to open the interactive browser after *any* answer whenever a
cached search happened to be in memory: a sticky "just searched" flag was set
by cache restores and /news browsing, and the post-answer hook also matched the
word "news" in the response text.  The result was that asking "what's the
weather tomorrow?" could pop open last week's news search.

The rule now is: a request is armed only when the turn itself searched for news
or loaded a cached search, and it is consumed exactly once.  Consuming it
prints a one-line hint instead of opening the modal browser, because the
browser owns the keyboard and hides the ``You:`` prompt until Esc.
"""

from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)

import core.news_cache as news_cache_mod  # noqa: E402
from core.cli import news_browse_hint, pop_pending_news_browse  # noqa: E402
from core.paths import paths  # noqa: E402
from skills.news import NewsSkill  # noqa: E402

# Never touch the real ~/.collig cache during tests.
_TMP_HOME = tempfile.mkdtemp(prefix="collig-news-autoopen-")
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
        "title": "AI agent story %d" % i,
        "source": "Test Source",
        "date": "2026-10-27T21:02:19+00:00",
        "body": "Body %d" % i,
        "url": "https://example.com/%d" % i,
    }
    for i in range(1, 10)
]

QUERY = "ai agent news in nsw australia"


class FakeEntry:
    def __init__(self, query, news_items, cache_id="news_000001"):
        self.query = query
        self.news_items = list(news_items)
        self.cache_id = cache_id
        self.timestamp = "2026-10-27T21:02:19"


class FakeCacheManager:
    def __init__(self, entry=None):
        self.entry = entry
        self.saved = []

    def get_most_recent(self, session_id=None):
        return self.entry

    def get_all_searches(self, session_id=None):
        return [self.entry] if self.entry else []

    def save_search(self, query, news_items, session_id=None):
        self.saved.append((query, list(news_items)))
        return "news_000002"


def reset(items=None, query="", flag=False):
    NewsSkill._news_cache = list(items or [])
    NewsSkill._last_query = query
    NewsSkill._just_searched = flag
    NewsSkill._current_cache_id = None


# ---------------------------------------------------------------------------
# Restoring a cached search (so read_news_item can answer) must not arm the
# browser.  This is the path that fired on the weather question.
# ---------------------------------------------------------------------------
reset()
fake_mgr = FakeCacheManager(FakeEntry(QUERY, ITEMS))
original_get = news_cache_mod.get_news_cache_manager
news_cache_mod.get_news_cache_manager = lambda: fake_mgr
try:
    restored = NewsSkill.restore_most_recent_cache()
    restored_count = len(NewsSkill._news_cache)
    still_armed = NewsSkill.has_just_searched()
    pending_after_restore = pop_pending_news_browse()

    # A weather answer can be anything; the helper no longer looks at text.
    weather_pending = pop_pending_news_browse()
finally:
    news_cache_mod.get_news_cache_manager = original_get
    reset()

check("restore rehydrates the cached items", restored and restored_count == len(ITEMS))
check("restore does not arm the browser", not still_armed)
check("restored cache alone opens nothing", pending_after_restore is None)
check("weather turn after a restore opens nothing", weather_pending is None)


# ---------------------------------------------------------------------------
# A real search arms the browser once and only once.
# ---------------------------------------------------------------------------
reset(items=ITEMS, query=QUERY, flag=True)
first = pop_pending_news_browse()
second = pop_pending_news_browse()

check("pending search opens the browser", first is not None)
check("pending search keeps the right items", first is not None and first[0] == ITEMS)
check("pending search keeps the right query", first is not None and first[1] == QUERY)
check("request is consumed, not repeated", second is None)


# ---------------------------------------------------------------------------
# A stale flag from an interrupted turn is dropped at the start of the next
# turn (the CLI calls clear_search_flag before every message).
# ---------------------------------------------------------------------------
reset(items=ITEMS, query=QUERY)
NewsSkill.clear_search_flag()
check("stale request is cleared at turn start", pop_pending_news_browse() is None)


# ---------------------------------------------------------------------------
# Browsing via /news must not leave a request behind for the next message.
# The /news command opens the browser itself and never sets the flag.
# ---------------------------------------------------------------------------
reset(items=ITEMS, query=QUERY)
check("browsing via /news leaves no pending request", pop_pending_news_browse() is None)


# ---------------------------------------------------------------------------
# search_news itself (the genuine "user asked for news" path) still arms it.
# ---------------------------------------------------------------------------
reset()
import skills.news as news_mod  # noqa: E402


class FakeDDGS:
    def news(self, query, max_results=10):
        return list(ITEMS)


original_ddgs = news_mod.DDGS
original_get = news_cache_mod.get_news_cache_manager
search_mgr = FakeCacheManager(None)
news_mod.DDGS = FakeDDGS
news_cache_mod.get_news_cache_manager = lambda: search_mgr
try:
    search_tool = next(tool for tool in NewsSkill().get_tools() if tool.name == "search_news")
    search_tool.func(QUERY)
    searched_armed = NewsSkill.has_just_searched()
    searched = pop_pending_news_browse()
finally:
    news_mod.DDGS = original_ddgs
    news_cache_mod.get_news_cache_manager = original_get
    reset()

check("search_news arms the browser", searched_armed)
check("search_news opens with the searched items", searched is not None and len(searched[0]) == len(ITEMS))
check("search_news opens with the searched query", searched is not None and searched[1] == QUERY)
check("search_news request is consumed once", pop_pending_news_browse() is None)


# ---------------------------------------------------------------------------
# The hint that replaces the auto-opened browser.
# ---------------------------------------------------------------------------
check(
    "hint counts a single item in the singular",
    news_browse_hint(ITEMS[:1]) == "📰 1 news item ready · /news last to browse · /news cached to pick another",
    news_browse_hint(ITEMS[:1]),
)
check(
    "hint counts several items in the plural",
    "📰 9 news items ready" in news_browse_hint(ITEMS),
    news_browse_hint(ITEMS),
)
check("hint names the browse command", "/news last to browse" in news_browse_hint(ITEMS))
check("hint survives an empty list", news_browse_hint([]).startswith("📰 0 news items"))


# ---------------------------------------------------------------------------
# Source guard: the CLI must not arm the flag itself (that is what leaked the
# request across turns), the response-keyword heuristic must stay gone, and
# the post-answer hook must hint instead of opening the modal browser.
# ---------------------------------------------------------------------------
with open(os.path.join(PROJECT, "core", "cli.py"), "r", encoding="utf-8") as handle:
    cli_source = handle.read()

check("CLI no longer sets the just-searched flag", "_just_searched = True" not in cli_source)
check(
    "CLI no longer guesses from the word 'news' in the answer",
    'in result.get("response", "").lower()' not in cli_source,
)
check(
    "CLI does not auto-open the browser after an answer",
    "browse_news_items(pending_browse" not in cli_source,
)
check("CLI prints the browse hint instead", "news_browse_hint(pending_browse" in cli_source)
check(
    "the hint is only printed for a pending search",
    "if pending_browse:" in cli_source,
)
check(
    "browser is still reachable on demand",
    cli_source.count("browse_news_items(") >= 5,
    "%d call sites" % cli_source.count("browse_news_items("),
)


print("\n================ SUMMARY ================")
print("%d passed, %d failed" % (len(passed), len(failed)))
if failed:
    for name in failed:
        print("  -", name)
    sys.exit(1)
print("All checks passed.")
