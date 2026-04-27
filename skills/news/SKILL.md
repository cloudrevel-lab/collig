---
name: News Search
description: Search and browse news articles with semantic caching and search
version: 1.0.0
author: Collig Team
license: MIT

tools:
  - name: search_news
    description: Search for news articles based on a query
  - name: read_news_item
    description: Read details of a specific news item from search results
  - name: save_news_search
    description: Save the current news search to cache
  - name: list_cached_news
    description: List all cached news searches
  - name: load_cached_news
    description: Load a cached news search by number
  - name: check_news_cache
    description: Check the current news cache status

config:
  required: []
  optional: []

triggers:
  - news
  - headlines
  - current events
  - search news
---

# News Search Skill

Provides news search capabilities using DuckDuckGo News API with semantic caching for efficient retrieval.

## Usage

Use this skill when the user wants to:
- Search for news articles on a topic
- Read details of specific news items
- Save and reload news searches
- Browse cached news searches

## Examples

- "Search for local news in Sydney"
- "Read news item 1"
- "Save this search"
- "List my cached news searches"
- "Load cached news 1"

## Tools

### search_news(query: str) -> str

Search for news articles based on a query.

**Parameters:**
- `query`: Search query (e.g., "local news in Sydney today")

**Returns:** Numbered list of news items with titles, sources, and dates.

### read_news_item(index: int) -> str

Read the title and content summary of a specific news item.

**Parameters:**
- `index`: The number of the news item to read (1-based)

**Returns:** Full details including title, source, summary, and link.

### save_news_search() -> str

Save the current news search to the cache for later retrieval.

**Returns:** Confirmation with cache ID.

### list_cached_news() -> str

List all cached news searches.

**Returns:** List of saved searches with timestamps.

### load_cached_news(index: int) -> str

Load a cached news search by number.

**Parameters:**
- `index`: The number of the cached search to load (1-based)

**Returns:** Loaded news items from the cached search.

### check_news_cache() -> str

Check if there are news items currently available in memory.

**Returns:** Current cache status and available items.

## Notes

- Uses DuckDuckGo News API (no API key required)
- Automatically caches searches for later retrieval
- Cache persists across sessions via file system storage
