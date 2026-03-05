from typing import List, Dict, Any
from langchain_core.tools import tool
from ddgs import DDGS
from ..base import Skill
import json

try:
    from langchain_openai import OpenAIEmbeddings
    from langchain_chroma import Chroma
    from langchain_core.documents import Document
except ImportError:
    Chroma = None
    OpenAIEmbeddings = None

class NewsSkill(Skill):
    # Use class-level cache to ensure persistence across tool calls/copies
    _news_cache: List[Dict[str, Any]] = []
    _last_query: str = ""
    _just_searched: bool = False  # Flag to indicate a search just completed
    _current_cache_id: str = None  # ID of the current search if loaded from cache

    def __init__(self):
        super().__init__()
        # Ensure we start fresh or keep existing?
        # For a singleton-like behavior in CLI, keeping it is fine.
        # But if we want per-session isolation in a server, this would need a SessionManager-based approach.
        # Given the current CLI context, this is the fix.
        pass

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
        return "NewsSkill"

    def get_tools(self):
        @tool
        def search_news(query: str) -> str:
            """
            Search for news articles based on a query.
            Example: "local news in Sydney today"
            Returns a numbered list of news items.
            """
            try:
                # DDGS().news returns a generator, convert to list
                # Use positional argument for query as per ddgs package
                results = list(DDGS().news(query, max_results=10))

                if not results:
                    return f"No news found for '{query}'."

                NewsSkill._news_cache = results
                NewsSkill._last_query = query
                NewsSkill._just_searched = True
                NewsSkill._current_cache_id = None

                # Save to news cache manager
                try:
                    from core.news_cache import get_news_cache_manager
                    cache_mgr = get_news_cache_manager()
                    cache_mgr.save_search(query, results)
                except Exception:
                    pass  # Silently fail if cache save fails

                output = [f"Found {len(results)} news items for '{query}':\n"]
                for i, item in enumerate(results, 1):
                    title = item.get('title', 'No Title')
                    source = item.get('source', 'Unknown Source')
                    date = item.get('date', '')
                    output.append(f"{i}. [{source}] {title} ({date})")

                output.append("\nTo read a specific item, use the 'read_news_item' tool with the item number (e.g., 'read_news_item 1').")
                output.append("\nTip: Use 'list_cached_news' to browse previous searches, or 'load_cached_news' to reload one.")
                return "\n".join(output)

            except Exception as e:
                return f"Error searching news: {str(e)}"

        @tool
        def read_news_item(index: int) -> str:
            """
            Read the title and content summary of a specific news item from the last search results.
            Use this when the user asks to see details, read, show, or get more information about a specific news item by number.
            Examples: "read 1", "show me detail for item 2", "get more info on article 3", "what about item 4", "tell me about number 5".
            Args:
                index: The number of the news item to read (1-based).
            """
            if not NewsSkill._news_cache:
                return "No news items available. Please search for news first or load a cached search."

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
            Use this to save a search you want to come back to later.
            """
            if not NewsSkill._news_cache:
                return "No news items available to save. Please search for news first."

            try:
                from core.news_cache import get_news_cache_manager
                cache_mgr = get_news_cache_manager()
                cache_id = cache_mgr.save_search(NewsSkill._last_query, NewsSkill._news_cache)
                return f"✅ Successfully saved news search! (ID: {cache_id})\nUse 'list_cached_news' to browse saved searches, or 'load_cached_news' to reload this one."
            except Exception as e:
                return f"Error saving news search: {str(e)}"

        @tool
        def list_cached_news() -> str:
            """
            List all cached news searches.
            Shows all previously saved news searches with their timestamps.
            """
            try:
                from core.news_cache import get_news_cache_manager
                cache_mgr = get_news_cache_manager()
                searches = cache_mgr.get_all_searches()

                if not searches:
                    return "No cached news searches found. Search for news and use 'save_news_search' to save it!"

                output = ["📰 Saved News Searches:\n"]
                for i, entry in enumerate(searches, 1):
                    output.append(f"{i}. {entry.get_display_title()}")

                output.append("\nTo load a search, say 'load_cached_news 1' (or whatever number you want).")
                output.append("You can also say 'load most recent news' to load the most recent one.")
                return "\n".join(output)

            except Exception as e:
                return f"Error listing cached news: {str(e)}"

        @tool
        def load_cached_news(index: int) -> str:
            """
            Load a cached news search by number.
            Use after 'list_cached_news' to load a specific search.
            Example: "load_cached_news 1" loads the first search in the list.
            Args:
                index: The number of the cached search to load (1-based, from list_cached_news)
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
            Check if there are news items currently available in memory from a recent search.
            Use this to understand the context when user asks about news items by number.
            Returns information about available cached news items.
            """
            if not NewsSkill._news_cache:
                return "No news items currently available in memory. Search for news first, or load a cached search with 'load_cached_news'."

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

            output.append("\nTip: Use 'list_cached_news' to see all saved searches, or 'save_news_search' to save the current one.")
            return "\n".join(output)

        return [search_news, read_news_item, save_news_search, list_cached_news, load_cached_news, check_news_cache]
