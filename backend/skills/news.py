from typing import List, Dict, Any
from langchain_core.tools import tool
from ddgs import DDGS
from .base import Skill

class NewsSkill(Skill):
    # Use class-level cache to ensure persistence across tool calls/copies
    _news_cache: List[Dict[str, Any]] = []

    def __init__(self):
        super().__init__()
        # Ensure we start fresh or keep existing?
        # For a singleton-like behavior in CLI, keeping it is fine.
        # But if we want per-session isolation in a server, this would need a SessionManager-based approach.
        # Given the current CLI context, this is the fix.
        pass

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
            Read the title and content summary of a specific news item from the last search.
            Use this when the user asks to "read" a news item by number (e.g., "read 1", "read article 2").
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

        return [search_news, read_news_item]
