from typing import Dict, Any, List, Optional
import os
import datetime
import json
from langchain_core.tools import tool, BaseTool
from .base import Skill
from core.paths import paths

try:
    from langchain_openai import OpenAIEmbeddings
    from langchain_chroma import Chroma
    from langchain_core.documents import Document
except ImportError:
    Chroma = None
    OpenAIEmbeddings = None

class CacheSkill(Skill):
    def __init__(self):
        super().__init__()
        self.vectorstore = None
        self.persist_directory = paths.get_skill_data_dir("cache")
        self.last_retrieved_ids = []

        self._initialize_store()

    @property
    def name(self) -> str:
        return "Cache"

    @property
    def description(self) -> str:
        return "Stores and retrieves cached content (news, search results, articles) using a local vector database for offline access."

    def _initialize_store(self):
        api_key = self.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")

        if not api_key:
            return

        if Chroma and not self.vectorstore:
            try:
                self.embeddings = OpenAIEmbeddings(api_key=api_key)
                self.vectorstore = Chroma(
                    persist_directory=self.persist_directory,
                    embedding_function=self.embeddings,
                    collection_name="user_cache"
                )
            except Exception as e:
                print(f"Failed to initialize Chroma for cache: {e}")

    @property
    def required_config(self) -> List[str]:
        return ["OPENAI_API_KEY"]

    def get_tools(self) -> List[BaseTool]:

        @tool
        def cache_content(
            content: str,
            content_type: str = "general",
            title: str = "",
            source: str = "",
            url: str = "",
            tags: str = "",
            original_query: str = ""
        ) -> str:
            """
            Save content to the cache for later offline access.
            Args:
                content: The main content to cache (e.g., news article, search result).
                content_type: Type of content (e.g., "news", "search_result", "article", "general").
                title: Optional title for the cached item.
                source: Optional source name (e.g., "BBC", "CNN").
                url: Optional URL link.
                tags: Optional comma-separated tags for categorization.
                original_query: The original search query that led to this content.
            """
            if not self.vectorstore:
                return "Cache system not initialized. Check OPENAI_API_KEY."

            meta = {
                "content_type": content_type,
                "title": title,
                "source": source,
                "url": url,
                "tags": tags,
                "original_query": original_query,
                "timestamp": datetime.datetime.now().isoformat(),
                "type": "cached_content"
            }

            search_content = f"Title: {title}\nContent: {content}\nSource: {source}\nTags: {tags}\nQuery: {original_query}"

            self.vectorstore.add_documents([Document(page_content=search_content, metadata=meta)])

            return f"✅ Content cached successfully (Type: {content_type})"

        @tool
        def cache_news_list(news_items: str, query: str = "") -> str:
            """
            Cache a list of news articles for offline access.
            Args:
                news_items: A JSON string or formatted text containing news items.
                query: The original search query used to find these news items.
            """
            if not self.vectorstore:
                return "Cache system not initialized. Check OPENAI_API_KEY."

            try:
                items = []
                if news_items.strip().startswith('[') or news_items.strip().startswith('{'):
                    items = json.loads(news_items)
                else:
                    return "Please provide news items in JSON format."

                if not isinstance(items, list):
                    items = [items]

                cached_count = 0
                for item in items:
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
                        "original_query": query,
                        "timestamp": datetime.datetime.now().isoformat(),
                        "type": "cached_content"
                    }

                    search_content = f"Title: {title}\nContent: {body}\nSource: {source}\nDate: {date}\nQuery: {query}"

                    self.vectorstore.add_documents([Document(page_content=search_content, metadata=meta)])
                    cached_count += 1

                return f"✅ Successfully cached {cached_count} news articles."

            except json.JSONDecodeError:
                return "Invalid JSON format. Please provide news items as a valid JSON array."
            except Exception as e:
                return f"Error caching news list: {str(e)}"

        @tool
        def list_cache(content_type: str = "", limit: int = 10) -> str:
            """
            List recently cached items.
            Args:
                content_type: Filter by content type (e.g., "news", "article"). Leave empty for all types.
                limit: Maximum number of items to show (default: 10).
            """
            if not self.vectorstore:
                return "Cache system not initialized."

            try:
                collection = self.vectorstore._collection

                where_clause = {"type": "cached_content"}
                if content_type:
                    where_clause["content_type"] = content_type

                data = collection.get(where=where_clause, limit=100, include=["documents", "metadatas"])

                docs = data.get("documents", [])
                metas = data.get("metadatas", [])
                ids = data.get("ids", [])

                combined = []
                for d, m, i in zip(docs, metas, ids):
                    combined.append({"content": d, "metadata": m, "id": i})

                combined.sort(key=lambda x: x["metadata"].get("timestamp", ""), reverse=True)
                recent = combined[:limit]

                self.last_retrieved_ids = [r["id"] for r in recent]

                if not recent:
                    if content_type:
                        return f"No cached items found for type: {content_type}"
                    return "No cached items found."

                output = [f"Recent Cached Items ({content_type or 'All Types'}):"]
                for idx, item in enumerate(recent, 1):
                    meta = item["metadata"]
                    title = meta.get("title", "No Title")
                    content_type = meta.get("content_type", "general")
                    source = meta.get("source", "")
                    ts = meta.get("timestamp", "")[:16].replace("T", " ")

                    if source:
                        output.append(f"{idx}. [{ts}] {title} ({source}) - Type: {content_type}")
                    else:
                        output.append(f"{idx}. [{ts}] {title} - Type: {content_type}")

                return "\n".join(output)
            except Exception as e:
                return f"Error listing cache: {str(e)}"

        @tool
        def search_cache(query: str, content_type: str = "", k: int = 5) -> str:
            """
            Search cached items by semantic similarity.
            Args:
                query: The search query.
                content_type: Filter by content type (e.g., "news"). Leave empty for all types.
                k: Maximum number of results to return (default: 5).
            """
            if not self.vectorstore:
                return "Cache system not initialized."

            try:
                if content_type:
                    collection = self.vectorstore._collection
                    data = collection.get(where={"content_type": content_type}, include=["documents", "metadatas", "ids"])

                    if not data.get("ids"):
                        return f"No cached items found for type: {content_type}"

                    docs = []
                    for doc, meta in zip(data["documents"], data["metadatas"]):
                        docs.append(Document(page_content=doc, metadata=meta))

                    from langchain_community.vectorstores import Chroma as LCChroma
                    temp_store = LCChroma.from_documents(docs, self.embeddings)
                    results = temp_store.similarity_search(query, k=min(k, len(docs)))
                else:
                    results = self.vectorstore.similarity_search(query, k=k)

                if not results:
                    return "No matching cached items found."

                output = [f"Found {len(results)} matches for '{query}':"]
                for idx, doc in enumerate(results, 1):
                    meta = doc.metadata
                    title = meta.get("title", "No Title")
                    source = meta.get("source", "")
                    content_type = meta.get("content_type", "general")

                    if source:
                        output.append(f"{idx}. {title} ({source}) - Type: {content_type}")
                    else:
                        output.append(f"{idx}. {title} - Type: {content_type}")

                return "\n".join(output)
            except Exception as e:
                return f"Error searching cache: {str(e)}"

        @tool
        def get_cache_item(index: int) -> str:
            """
            Get the full details of a specific cached item by index from the last 'list_cache' output.
            Args:
                index: The index number (1-based) from the most recent list.
            """
            if not self.vectorstore:
                return "Cache system not initialized."

            if not self.last_retrieved_ids:
                return "I don't have a recent list of cached items. Please call 'list_cache' first."

            if index < 1 or index > len(self.last_retrieved_ids):
                return f"Invalid index. Please choose a number between 1 and {len(self.last_retrieved_ids)}."

            try:
                collection = self.vectorstore._collection
                item_id = self.last_retrieved_ids[index - 1]
                data = collection.get(ids=[item_id], include=["documents", "metadatas"])

                if not data.get("ids"):
                    return "Item not found."

                doc = data["documents"][0]
                meta = data["metadatas"][0]

                title = meta.get("title", "No Title")
                source = meta.get("source", "")
                url = meta.get("url", "")
                content_type = meta.get("content_type", "general")
                ts = meta.get("timestamp", "")[:16].replace("T", " ")
                tags = meta.get("tags", "")

                output = [
                    f"**Title:** {title}",
                    f"**Type:** {content_type}",
                    f"**Source:** {source}",
                    f"**Cached:** {ts}",
                ]

                if url:
                    output.append(f"**URL:** {url}")
                if tags:
                    output.append(f"**Tags:** {tags}")

                output.append(f"\n**Content:**\n{doc}")

                return "\n".join(output)
            except Exception as e:
                return f"Error retrieving cache item: {str(e)}"

        @tool
        def delete_cache(indices: List[int]) -> str:
            """
            Delete cached items by their index numbers from the most recent 'list_cache' output.
            Args:
                indices: List of integer indices to delete (1-based).
            """
            if not self.vectorstore:
                return "Cache system not initialized."

            if not self.last_retrieved_ids:
                return "I don't have a recent list of cached items. Please call 'list_cache' first."

            ids_to_delete = []
            deleted_indices = []

            for idx in indices:
                if 1 <= idx <= len(self.last_retrieved_ids):
                    ids_to_delete.append(self.last_retrieved_ids[idx - 1])
                    deleted_indices.append(idx)

            if not ids_to_delete:
                return "No valid indices provided."

            try:
                self.vectorstore.delete(ids=ids_to_delete)
                return f"✅ Deleted cached items at indices: {deleted_indices}"
            except Exception as e:
                return f"Error deleting cache items: {str(e)}"

        @tool
        def clear_cache(content_type: str = "") -> str:
            """
            Clear all cached items or items of a specific type.
            Args:
                content_type: Clear only items of this type (e.g., "news"). Leave empty to clear all.
            """
            if not self.vectorstore:
                return "Cache system not initialized."

            try:
                collection = self.vectorstore._collection

                where_clause = {"type": "cached_content"}
                if content_type:
                    where_clause["content_type"] = content_type

                data = collection.get(where=where_clause, include=["ids"])
                ids = data.get("ids", [])

                if not ids:
                    if content_type:
                        return f"No cached items found for type: {content_type}"
                    return "No cached items found."

                self.vectorstore.delete(ids=ids)

                if content_type:
                    return f"✅ Cleared all cached items of type: {content_type} ({len(ids)} items)"
                return f"✅ Cleared all cached items ({len(ids)} items)"
            except Exception as e:
                return f"Error clearing cache: {str(e)}"

        return [
            cache_content,
            cache_news_list,
            list_cache,
            search_cache,
            get_cache_item,
            delete_cache,
            clear_cache
        ]
