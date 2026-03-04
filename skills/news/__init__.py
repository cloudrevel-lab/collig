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
                print(f"DEBUG: NewsSkill._news_cache updated. Size: {len(NewsSkill._news_cache)} ID: {id(NewsSkill._news_cache)} ClassID: {id(NewsSkill)}")

                output = [f"Found {len(results)} news items for '{query}':\n"]
                for i, item in enumerate(results, 1):
                    title = item.get('title', 'No Title')
                    source = item.get('source', 'Unknown Source')
                    date = item.get('date', '')
                    output.append(f"{i}. [{source}] {title} ({date})")

                output.append("\nTo read a specific item, use the 'read_news_item' tool with the item number (e.g., 'read_news_item 1').")
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
            print(f"DEBUG: read_news_item called. Cache Size: {len(NewsSkill._news_cache)} ID: {id(NewsSkill._news_cache)} ClassID: {id(NewsSkill)}")
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
        def cache_news_list() -> str:
            """
            Cache the current news list for offline access.
            This saves all news items from the last search to the local cache.
            """
            if not NewsSkill._news_cache:
                return "No news items available to cache. Please search for news first."

            try:
                from core.paths import paths
                import os
                import datetime

                api_key = self.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
                if not api_key:
                    return "Cache system requires OPENAI_API_KEY to be set."

                if not Chroma or not OpenAIEmbeddings:
                    return "Cache system dependencies not available."

                persist_directory = paths.get_skill_data_dir("cache")
                embeddings = OpenAIEmbeddings(api_key=api_key)
                vectorstore = Chroma(
                    persist_directory=persist_directory,
                    embedding_function=embeddings,
                    collection_name="user_cache"
                )

                cached_count = 0
                for item in NewsSkill._news_cache:
                    title = item.get('title', '')
                    body = item.get('body', '')
                    source = item.get('source', '')
                    url = item.get('url', '')
                    date = item.get('date', '')

                    meta = {
                        "content_type": "news",
                        "title": title,
                        "source": source,
                        "url": url,
                        "date": date,
                        "original_query": NewsSkill._last_query,
                        "timestamp": datetime.datetime.now().isoformat(),
                        "type": "cached_content"
                    }

                    search_content = f"Title: {title}\nContent: {body}\nSource: {source}\nDate: {date}\nQuery: {NewsSkill._last_query}"

                    vectorstore.add_documents([Document(page_content=search_content, metadata=meta)])
                    cached_count += 1

                return f"✅ Successfully cached {cached_count} news articles. You can now access them offline using the cache tools."

            except Exception as e:
                return f"Error caching news list: {str(e)}"

        @tool
        def check_news_cache() -> str:
            """
            Check if there are news items currently available in memory from a recent search.
            Use this to understand the context when user asks about news items by number.
            Returns information about available cached news items.
            """
            if not NewsSkill._news_cache:
                return "No news items currently available in memory. User needs to search for news first."

            count = len(NewsSkill._news_cache)
            query = NewsSkill._last_query or "unknown"

            output = [f"News cache status: {count} items available from recent search."]
            output.append(f"Last search query: '{query}'")
            output.append(f"Available item numbers: 1 to {count}")
            output.append("\nRecent items:")
            for i, item in enumerate(NewsSkill._news_cache[:5], 1):
                title = item.get('title', 'No Title')
                source = item.get('source', 'Unknown')
                output.append(f"  {i}. [{source}] {title}")

            if count > 5:
                output.append(f"  ... and {count - 5} more items")

            return "\n".join(output)

        return [search_news, read_news_item, cache_news_list, check_news_cache]
