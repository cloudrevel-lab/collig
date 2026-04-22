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
        return "Search the web for information using DuckDuckGo. Use this as the PRIMARY tool for answering questions about current events, facts, weather, news, products, people, places, or anything requiring real-time information. The agent will automatically synthesize answers from results."

    def get_tools(self):
        @tool
        def web_search(query: str) -> str:
            """
            Search the web for information - this is your PRIMARY tool for answering questions.
            Use this for: current events, weather, news, facts, products, people, places, research, how-to guides, documentation, or ANY question requiring real-time or factual information.
            After getting results, synthesize a natural answer from the information found.
            Args:
                query: The search query - use specific, focused terms for best results
            """
            try:
                results = list(DDGS().text(query, max_results=10))

                if not results:
                    return f"No results found for '{query}'. Try a different search term."

                WebSearchSkill._search_cache = results
                WebSearchSkill._last_query = query
                WebSearchSkill._just_searched = True

                # Format results for natural synthesis
                output = [f"🔍 Search results for '{query}':\n"]
                for i, item in enumerate(results, 1):
                    title = item.get('title', 'No Title')
                    href = item.get('href', '')
                    body = item.get('body', 'No description available.')
                    source = href.split('/')[2] if href else 'Unknown'
                    output.append(f"{i}. **{title}** ({source})")
                    output.append(f"   {body}")
                    output.append(f"   Source: {href}\n")

                output.append("\n💡 Tip: Synthesize these results into a helpful, natural answer for the user.")
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
