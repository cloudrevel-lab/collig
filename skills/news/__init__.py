"""
News Search Skill - Portable implementation following agentskills.io spec.

Search and browse news articles with semantic caching and search.
"""

import os
from typing import List, Dict, Any
from langchain_core.tools import tool
from skills.base import Skill
from ddgs import DDGS


class NewsSkill(Skill):
    """Search and browse news articles with semantic caching."""

    # Class-level cache for persistence across tool calls
    _news_cache: List[Dict[str, Any]] = []
    _last_query: str = ""
    _just_searched: bool = False
    _current_cache_id: str = None

    def __init__(self, skill_root=None):
        super().__init__(skill_root)

    @classmethod
    def get_news_cache(cls):
        """Get the current news cache."""
        return cls._news_cache

    @classmethod
    def get_last_query(cls):
        """Get the last search query."""
        return cls._last_query

    @classmethod
    def has_just_searched(cls):
        """Check if a search just completed."""
        return cls._just_searched

    @classmethod
    def clear_search_flag(cls):
        """Clear the just-searched flag."""
        cls._just_searched = False

    @classmethod
    def restore_most_recent_cache(cls) -> bool:
        """Rehydrate the in-memory list from disk after a restart.

        read_news_item used to depend only on the class-level cache, which is
        empty after /restart or a new process. The cached search is still on
        disk, so users who resume a conversation and ask for item 1 should get
        the list they were just looking at.
        """
        if cls._news_cache:
            return True
        try:
            from core.news_cache import get_news_cache_manager

            session_id = os.getenv("COLLIG_SESSION_ID") or None
            entry = get_news_cache_manager().get_most_recent(session_id=session_id)
            if entry is None or not entry.news_items:
                return False
            cls._news_cache = entry.news_items
            cls._last_query = entry.query
            # Deliberately do NOT mark this as "just searched": restoring a
            # cache so an item can be read is not a request to browse, and a
            # sticky flag here reopened the news browser on later, unrelated
            # turns (for example a weather question).
            cls._current_cache_id = entry.cache_id
            return True
        except Exception:
            return False

    @property
    def name(self) -> str:
        return "News Search"

    @property
    def description(self) -> str:
        return "Search and browse news articles with semantic caching"

    @property
    def triggers(self) -> List[str]:
        return ["news", "headlines", "current events", "search news"]

    def get_tools(self):
        @tool
        def search_news(query: str) -> str:
            """
            Search for news articles based on a query.

            Args:
                query: Search query (e.g., "local news in Sydney today")
            """
            try:
                results = list(DDGS().news(query, max_results=10))

                if not results:
                    return f"No news found for '{query}'."

                NewsSkill._news_cache = results
                NewsSkill._last_query = query
                NewsSkill._just_searched = True
                NewsSkill._current_cache_id = None

                # Every search is cached automatically.  Reopening it later
                # should not require searching again.
                cache_id = None
                try:
                    from core.news_cache import get_news_cache_manager

                    cache_mgr = get_news_cache_manager()
                    cache_id = cache_mgr.save_search(query, results, session_id=os.getenv("COLLIG_SESSION_ID") or None)
                    NewsSkill._current_cache_id = cache_id
                except Exception:
                    pass

                output = [f"Found {len(results)} news items for '{query}':\n"]
                for i, item in enumerate(results, 1):
                    title = item.get("title", "No Title")
                    source = item.get("source", "Unknown Source")
                    date = item.get("date", "")
                    output.append(f"{i}. [{source}] {title} ({date})")

                output.append("\nTo read a specific item, use 'read_news_item' with the item number.")
                if cache_id:
                    output.append("📌 Saved to cache. Reopen it later with /news last (or /news cached to pick one).")
                else:
                    output.append("Tip: Use 'list_cached_news' to browse previous searches.")
                return "\n".join(output)

            except Exception as e:
                return f"Error searching news: {str(e)}"

        @tool
        def read_news_item(index: int) -> str:
            """
            Read the title and content summary of a specific news item.

            If the in-memory list is empty (for example after /restart or a
            resumed session), the most recent cached search is loaded first.

            Args:
                index: The number of the news item to read (1-based)
            """
            was_in_memory = bool(NewsSkill._news_cache)
            if not NewsSkill.restore_most_recent_cache():
                return "No news items available. Please search for news first, or use /news last to reopen a cached search."

            if index < 1 or index > len(NewsSkill._news_cache):
                return f"Invalid index. Please choose a number between 1 and {len(NewsSkill._news_cache)}."

            item = NewsSkill._news_cache[index - 1]
            title = item.get("title", "No Title")
            body = item.get("body", "No content summary available.")
            source = item.get("source", "Unknown Source")
            url = item.get("url", "#")
            date = item.get("date", "")

            prefix = ""
            if not was_in_memory:
                prefix = f'(Loaded from cached search: "{NewsSkill._last_query}")\n\n'
            return (
                prefix
                + f"**Title:** {title}\n"
                + f"**Source:** {source} ({date})\n"
                + f"**Summary:** {body}\n"
                + f"**Link:** {url}"
            )

        @tool
        def save_news_search() -> str:
            """
            Save the current news search to the cache for later retrieval.
            """
            if not NewsSkill._news_cache:
                return "No news items available to save. Please search for news first."

            try:
                from core.news_cache import get_news_cache_manager

                cache_mgr = get_news_cache_manager()
                cache_id = cache_mgr.save_search(
                    NewsSkill._last_query,
                    NewsSkill._news_cache,
                    session_id=os.getenv("COLLIG_SESSION_ID") or None,
                )
                NewsSkill._current_cache_id = cache_id
                return f"✅ Successfully saved news search! (ID: {cache_id})\n   Reopen it with /news last."
            except Exception as e:
                return f"Error saving news search: {str(e)}"

        @tool
        def list_cached_news() -> str:
            """
            List all cached news searches.
            """
            try:
                from core.news_cache import get_news_cache_manager

                cache_mgr = get_news_cache_manager()
                searches = cache_mgr.get_all_searches()

                if not searches:
                    return "No cached news searches found."

                output = ["📰 Saved News Searches:\n"]
                for i, entry in enumerate(searches, 1):
                    output.append(f"{i}. {entry.get_display_title()}")

                output.append("\nTo load a search, say 'load_cached_news 1'.")
                return "\n".join(output)

            except Exception as e:
                return f"Error listing cached news: {str(e)}"

        @tool
        def load_cached_news(index: int) -> str:
            """
            Load a cached news search by number.

            Args:
                index: The number of the cached search to load (1-based)
            """
            try:
                from core.news_cache import get_news_cache_manager

                cache_mgr = get_news_cache_manager()
                searches = cache_mgr.get_all_searches()

                if not searches:
                    return "No cached news searches found."

                if index < 1 or index > len(searches):
                    return f"Invalid index. Please choose a number between 1 and {len(searches)}."

                entry = searches[index - 1]
                NewsSkill._news_cache = entry.news_items
                NewsSkill._last_query = entry.query
                NewsSkill._just_searched = True
                NewsSkill._current_cache_id = entry.cache_id

                output = [f'✅ Loaded news search: "{entry.query}"\n']
                output.append(f"Found {len(entry.news_items)} news items:\n")

                for i, item in enumerate(entry.news_items, 1):
                    title = item.get("title", "No Title")
                    source = item.get("source", "Unknown Source")
                    date = item.get("date", "")
                    output.append(f"{i}. [{source}] {title} ({date})")

                return "\n".join(output)

            except Exception as e:
                return f"Error loading cached news: {str(e)}"

        @tool
        def check_news_cache() -> str:
            """
            Check if there are news items currently available in memory.
            """
            NewsSkill.restore_most_recent_cache()
            if not NewsSkill._news_cache:
                return "No news items currently available. Search for news first."

            count = len(NewsSkill._news_cache)
            query = NewsSkill._last_query or "unknown"
            source = "cached search" if NewsSkill._current_cache_id else "recent search"

            output = [f"News cache status: {count} items available ({source})."]
            output.append(f"Query: '{query}'")
            output.append(f"Available item numbers: 1 to {count}")
            output.append("\nRecent items:")
            for i, item in enumerate(NewsSkill._news_cache[:5], 1):
                title = item.get("title", "No Title")
                source = item.get("source", "Unknown")
                output.append(f"  {i}. [{source}] {title}")

            if count > 5:
                output.append(f"  ... and {count - 5} more items")

            output.append("\nTip: Use 'list_cached_news' to see all saved searches.")
            return "\n".join(output)

        return [search_news, read_news_item, save_news_search, list_cached_news, load_cached_news, check_news_cache]
