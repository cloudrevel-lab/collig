from typing import Dict, Any, List, Optional
import os
import datetime
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

class BookmarkSkill(Skill):
    def __init__(self):
        super().__init__()
        self.vectorstore = None
        # Use centralized data directory
        self.persist_directory = paths.get_skill_data_dir("bookmarks")
        self.last_retrieved_ids = [] # To store IDs of listed bookmarks for deletion by index

        # Ensure data directory exists
        # os.makedirs(self.persist_directory, exist_ok=True) # Handled by paths

        self._initialize_store()

    @property
    def name(self) -> str:
        return "Bookmarks"

    @property
    def description(self) -> str:
        return "Manages bookmarks (URLs) with descriptions and semantic search."

    def _initialize_store(self):
        """Attempts to initialize the vector store if configuration is available."""
        api_key = self.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")

        if not api_key:
            return

        # Initialize Vector Store
        if Chroma and not self.vectorstore:
            try:
                self.embeddings = OpenAIEmbeddings(api_key=api_key)
                self.vectorstore = Chroma(
                    persist_directory=self.persist_directory,
                    embedding_function=self.embeddings,
                    collection_name="user_bookmarks"
                )
            except Exception as e:
                print(f"Failed to initialize Chroma for bookmarks: {e}")

    @property
    def required_config(self) -> List[str]:
        return ["OPENAI_API_KEY"]

    def get_tools(self) -> List[BaseTool]:

        @tool
        def add_bookmark(url: str, description: str, tags: str = "") -> str:
            """
            Save a new bookmark to the database.
            Args:
                url: The URL of the bookmark.
                description: A description of what the bookmark is about.
                tags: Optional comma-separated tags (e.g., "coding, python").
            """
            if not self.vectorstore:
                return "Bookmark system not initialized. Check OPENAI_API_KEY."

            meta = {
                "url": url,
                "timestamp": datetime.datetime.now().isoformat(),
                "tags": tags,
                "type": "user_bookmark"
            }
            
            # Create content for semantic search: combination of desc, tags, and url
            search_content = f"URL: {url}\nDescription: {description}\nTags: {tags}"
            
            self.vectorstore.add_documents([Document(page_content=search_content, metadata=meta)])
            return f"✅ Bookmark saved: {url}"

        @tool
        def list_bookmarks() -> str:
            """
            List the 10 most recent bookmarks with timestamps.
            """
            if not self.vectorstore:
                return "Bookmark system not initialized."

            try:
                collection = self.vectorstore._collection
                data = collection.get(limit=100, include=["documents", "metadatas"])

                docs = data.get("documents", [])
                metas = data.get("metadatas", [])
                ids = data.get("ids", [])

                combined = []
                for d, m, i in zip(docs, metas, ids):
                    combined.append({"content": d, "metadata": m, "id": i})

                # Sort by timestamp descending
                combined.sort(key=lambda x: x["metadata"].get("timestamp", ""), reverse=True)
                recent = combined[:10]

                self.last_retrieved_ids = [r["id"] for r in recent]

                if not recent:
                    return "No bookmarks found."

                output = ["Recent Bookmarks:"]
                for idx, item in enumerate(recent, 1):
                    meta = item["metadata"]
                    url = meta.get("url", "No URL")
                    tags = meta.get("tags", "")
                    timestamp = meta.get("timestamp", "")
                    # Format timestamp for readability
                    try:
                        dt = datetime.datetime.fromisoformat(timestamp)
                        formatted_time = dt.strftime("%Y-%m-%d %H:%M")
                    except:
                        formatted_time = timestamp
                    # Extract description from content (simple parse or just show content)
                    # Content format: "URL: ...\nDescription: ...\nTags: ..."
                    content_lines = item["content"].split('\n')
                    desc = "No description"
                    for line in content_lines:
                        if line.startswith("Description:"):
                            desc = line.replace("Description:", "").strip()
                            break

                    output.append(f"{idx}. [{formatted_time}] {url} - {desc} (Tags: {tags})")

                return "\n".join(output)
            except Exception as e:
                return f"Error listing bookmarks: {e}"

        @tool
        def search_bookmarks(query: str) -> str:
            """
            Search for bookmarks by semantic similarity.
            Args:
                query: The search query (e.g., "python tutorials").
            """
            if not self.vectorstore:
                return "Bookmark system not initialized."

            results = self.vectorstore.similarity_search(query, k=5)
            
            if not results:
                return "No matching bookmarks found."

            output = [f"Found {len(results)} matches for '{query}':"]
            for doc in results:
                meta = doc.metadata
                url = meta.get("url", "No URL")
                # Parse description again
                content_lines = doc.page_content.split('\n')
                desc = "No description"
                for line in content_lines:
                    if line.startswith("Description:"):
                        desc = line.replace("Description:", "").strip()
                        break
                output.append(f"- [{url}] {desc}")
                
            return "\n".join(output)

        @tool
        def delete_bookmarks(indices: List[int]) -> str:
            """
            Delete bookmarks by their index number (e.g., [1, 2]) from the most recent 'list_bookmarks' output.
            Args:
                indices: List of integer indices of bookmarks to delete (1-based).
            """
            if not self.last_retrieved_ids:
                return "I don't have a recent list of bookmarks to delete from. Please call 'list_bookmarks' first."

            ids_to_delete = []
            deleted_indices = []

            for idx in indices:
                if 1 <= idx <= len(self.last_retrieved_ids):
                    ids_to_delete.append(self.last_retrieved_ids[idx - 1])
                    deleted_indices.append(idx)

            if not ids_to_delete:
                return "No valid indices provided."

            self.vectorstore.delete(ids=ids_to_delete)
            return f"Deleted bookmarks at indices: {deleted_indices}"

        @tool
        def search_bookmarks_by_date(start_date: str, end_date: str = "") -> str:
            """
            Search for bookmarks saved within a specific date range.
            Args:
                start_date: Start date in YYYY-MM-DD format (inclusive)
                end_date: End date in YYYY-MM-DD format (inclusive, optional - defaults to start_date)
            """
            if not self.vectorstore:
                return "Bookmark system not initialized."

            try:
                # Parse dates
                try:
                    start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
                    start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
                except ValueError:
                    return f"Invalid start_date format: {start_date}. Please use YYYY-MM-DD."

                if end_date:
                    try:
                        end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d")
                        end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
                    except ValueError:
                        return f"Invalid end_date format: {end_date}. Please use YYYY-MM-DD."
                else:
                    end_dt = start_dt.replace(hour=23, minute=59, second=59, microsecond=999999)

                collection = self.vectorstore._collection
                data = collection.get(limit=100, include=["documents", "metadatas"])

                docs = data.get("documents", [])
                metas = data.get("metadatas", [])
                ids = data.get("ids", [])

                # Filter by date range
                matches = []
                for d, m, i in zip(docs, metas, ids):
                    ts_str = m.get("timestamp", "")
                    if not ts_str:
                        continue
                    try:
                        bookmark_dt = datetime.datetime.fromisoformat(ts_str)
                        if start_dt <= bookmark_dt <= end_dt:
                            matches.append({"content": d, "metadata": m, "id": i})
                    except:
                        continue

                # Sort by timestamp descending
                matches.sort(key=lambda x: x["metadata"].get("timestamp", ""), reverse=True)

                self.last_retrieved_ids = [m["id"] for m in matches]

                if not matches:
                    date_range = f"{start_date} to {end_date}" if end_date else start_date
                    return f"No bookmarks found for date range: {date_range}"

                output = [f"Found {len(matches)} bookmark(s) for {start_date}" + (f" to {end_date}" if end_date else "") + ":"]
                for idx, item in enumerate(matches, 1):
                    meta = item["metadata"]
                    url = meta.get("url", "No URL")
                    tags = meta.get("tags", "")
                    timestamp = meta.get("timestamp", "")
                    try:
                        dt = datetime.datetime.fromisoformat(timestamp)
                        formatted_time = dt.strftime("%Y-%m-%d %H:%M")
                    except:
                        formatted_time = timestamp
                    content_lines = item["content"].split('\n')
                    desc = "No description"
                    for line in content_lines:
                        if line.startswith("Description:"):
                            desc = line.replace("Description:", "").strip()
                            break
                    output.append(f"{idx}. [{formatted_time}] {url} - {desc} (Tags: {tags})")

                return "\n".join(output)
            except Exception as e:
                return f"Error searching bookmarks by date: {e}"

        return [add_bookmark, list_bookmarks, search_bookmarks, delete_bookmarks, search_bookmarks_by_date]
