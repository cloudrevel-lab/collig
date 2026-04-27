"""
News Search Skill - Portable implementation following agentskills.io spec.

Search and browse news articles with semantic caching and search.
"""
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

                # Save to news cache manager if available
                try:
                    from core.news_cache import get_news_cache_manager
                    cache_mgr = get_news_cache_manager()
                    cache_mgr.save_search(query, results)
                except Exception:
                    pass

                output = [f"Found {len(results)} news items for '{query}':\n"]
                for i, item in enumerate(results, 1):
                    title = item.get('title', 'No Title')
                    source = item.get('source', 'Unknown Source')
                    date = item.get('date', '')
                    output.append(f"{i}. [{source}] {title} ({date})")

                output.append("\nTo read a specific item, use 'read_news_item' with the item number.")
                output.append("Tip: Use 'list_cached_news' to browse previous searches.")
                return "\n".join(output)

            except Exception as e:
                return f"Error searching news: {str(e)}"

        @tool
        def read_news_item(index: int) -> str:
            """
            Read the title and content summary of a specific news item.
            
            Args:
                index: The number of the news item to read (1-based)
            """
            if not NewsSkill._news_cache:
                return "No news items available. Please search for news first."

            if index < 1 or index > len(NewsSkill._news_cache):
                return f"Invalid index. Please choose a number between 1 and {len(NewsSkill._news_cache)}."

            item = NewsSkill._news_cache[index - 1]
            title = item.get('title', 'No Title')
            body = item.get('body', 'No content summary available.')
            source = item.get('source', 'Unknown Source')
            url = item.get('url', '#')
            date = item.get('date', '')

            return (
                f"**Title:** {title}\n"
                f"**Source:** {source} ({date})\n"
                f"**Summary:** {body}\n"
                f"**Link:** {url}"
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
                cache_id = cache_mgr.save_search(NewsSkill._last_query, NewsSkill._news_cache)
                return f"✅ Successfully saved news search! (ID: {cache_id})"
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

                output = [f"✅ Loaded news search: \"{entry.query}\"\n"]
                output.append(f"Found {len(entry.news_items)} news items:\n")

                for i, item in enumerate(entry.news_items, 1):
                    title = item.get('title', 'No Title')
                    source = item.get('source', 'Unknown Source')
                    date = item.get('date', '')
                    output.append(f"{i}. [{source}] {title} ({date})")

                return "\n".join(output)

            except Exception as e:
                return f"Error loading cached news: {str(e)}"

        @tool
        def check_news_cache() -> str:
            """
            Check if there are news items currently available in memory.
            """
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
                title = item.get('title', 'No Title')
                source = item.get('source', 'Unknown')
                output.append(f"  {i}. [{source}] {title}")

            if count > 5:
                output.append(f"  ... and {count - 5} more items")

            output.append("\nTip: Use 'list_cached_news' to see all saved searches.")
            return "\n".join(output)

        return [search_news, read_news_item, save_news_search, list_cached_news, load_cached_news, check_news_cache]
