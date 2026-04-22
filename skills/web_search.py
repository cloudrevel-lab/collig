from typing import List, Dict, Any
from langchain_core.tools import tool
from ddgs import DDGS
from .base import Skill


class WebSearchSkill(Skill):
    """Skill for performing general web searches using DuckDuckGo."""

    # Cache for search results
    _search_cache: List[Dict[str, Any]] = []
    _last_query: str = ""
    _just_searched: bool = False

    @property
    def name(self) -> str:
        return "WebSearch"

    @property
    def description(self) -> str:
        return "Search the web for information using DuckDuckGo. Use this for general queries, finding websites, or looking up information not covered by specialized skills like news."

    def get_tools(self):
        @tool
        def web_search(query: str) -> str:
            """
            Search the web for information using DuckDuckGo.
            Use this for general queries, finding websites, tutorials, documentation, or any information not covered by specialized skills.
            Args:
                query: The search query string
            """
            try:
                # DDGS().text returns a generator, convert to list
                results = list(DDGS().text(query, max_results=10))

                if not results:
                    return f"No results found for '{query}'."

                WebSearchSkill._search_cache = results
                WebSearchSkill._last_query = query
                WebSearchSkill._just_searched = True

                output = [f"Found {len(results)} web results for '{query}':\n"]
                for i, item in enumerate(results, 1):
                    title = item.get('title', 'No Title')
                    href = item.get('href', '')
                    body = item.get('body', 'No description available.')
                    output.append(f"{i}. [{title}]({href})")
                    output.append(f"   {body}\n")

                output.append("\nTo read more about a specific result, you can ask me to search for more details about it.")
                return "\n".join(output)

            except Exception as e:
                return f"Error searching the web: {str(e)}"

        @tool
        def read_search_result(index: int) -> str:
            """
            Read details of a specific search result from the last web search.
            Use this when the user asks to see details about a specific result by number.
            Args:
                index: The number of the search result to read (1-based)
            """
            if not WebSearchSkill._search_cache:
                return "No search results available. Please search the web first."

            if index < 1 or index > len(WebSearchSkill._search_cache):
                return f"Invalid index. Please choose a number between 1 and {len(WebSearchSkill._search_cache)}."

            item = WebSearchSkill._search_cache[index - 1]
            title = item.get('title', 'No Title')
            href = item.get('href', '#')
            body = item.get('body', 'No description available.')

            return f"**Title:** {title}\n**URL:** {href}\n**Summary:** {body}"

        @tool
        def check_search_status() -> str:
            """
            Check if there are search results currently available in memory.
            Use this to understand the context when user asks about search results by number.
            """
            if not WebSearchSkill._search_cache:
                return "No search results currently available in memory. Use web_search first."

            count = len(WebSearchSkill._search_cache)
            query = WebSearchSkill._last_query or "unknown"

            output = [f"Search cache status: {count} results available."]
            output.append(f"Query: '{query}'")
            output.append(f"Available result numbers: 1 to {count}")
            output.append("\nRecent results:")
            for i, item in enumerate(WebSearchSkill._search_cache[:5], 1):
                title = item.get('title', 'No Title')
                output.append(f"  {i}. {title}")

            if count > 5:
                output.append(f"  ... and {count - 5} more results")

            return "\n".join(output)

        return [web_search, read_search_result, check_search_status]
