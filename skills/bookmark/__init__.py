"""
Bookmark Skill - Allows saving and retrieving bookmarks.

Implements bookmark management using vector embeddings for semantic search.
"""
from typing import List, Dict, Any
import os
import datetime
from langchain_core.tools import tool, BaseTool
from skills.base import Skill

try:
    from langchain_openai import OpenAIEmbeddings
    from langchain_chroma import Chroma
    from langchain_core.documents import Document
except ImportError:
    Chroma = None
    OpenAIEmbeddings = None
    Document = None


class BookmarkSkill(Skill):
    """Provides bookmark management capabilities."""

    def __init__(self, skill_root=None):
        super().__init__(skill_root)
        self.vectorstore = None
        self.persist_directory = None
        self.embeddings = None
        self._initialized = False

    def configure(self, config: Dict[str, Any]):
        """
        Configure the skill and initialize the vector store.
        This is called after the skill is registered and config is available.
        """
        super().configure(config)
        self._initialized = False
        self._initialize_store()

    def _initialize_store(self):
        """Initialize the vector store if configuration is available."""
        if self._initialized and self.vectorstore is not None:
            return

        self._initialized = False

        llm_provider = self.config.get("LLM_PROVIDER", "openai")

        api_key = None
        base_url = None
        model_name = "text-embedding-ada-002"

        if llm_provider == "dashscope":
            api_key = self.config.get("DASHSCOPE_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
            endpoint_region = self.config.get("DASHSCOPE_ENDPOINT", "china")
            endpoints = {
                "china": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "singapore": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                "international": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
            }
            base_url = endpoints.get(endpoint_region, endpoints["china"])
            model_name = "text-embedding-v2"
        else:
            api_key = self.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")

        if not api_key:
            return

        if Chroma:
            try:
                if base_url:
                    self.embeddings = OpenAIEmbeddings(api_key=api_key, base_url=base_url, model=model_name)
                else:
                    self.embeddings = OpenAIEmbeddings(api_key=api_key, model=model_name)

                # Test embeddings with a simple query
                try:
                    self.embeddings.embed_query("test")
                except Exception as e:
                    # If embeddings fail, try falling back to OpenAI
                    if llm_provider == "dashscope":
                        openai_key = self.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
                        if openai_key:
                            print(f"DashScope embeddings unavailable ({e}), falling back to OpenAI for embeddings")
                            self.embeddings = OpenAIEmbeddings(api_key=openai_key, model="text-embedding-ada-002")
                            base_url = None
                        else:
                            raise
                    else:
                        raise

                persist_dir = self.persist_directory or os.path.join(
                    os.path.expanduser("~"), ".collig", "data", "bookmarks"
                )
                self.vectorstore = Chroma(
                    persist_directory=persist_dir,
                    embedding_function=self.embeddings,
                    collection_name="user_bookmarks"
                )
                self._initialized = True
            except Exception as e:
                print(f"Failed to initialize Chroma for bookmarks: {e}")

    @property
    def name(self) -> str:
        return "Bookmarks"

    @property
    def description(self) -> str:
        return "Save, search, and manage bookmarks"

    @property
    def triggers(self) -> List[str]:
        return ["bookmark", "save link", "saved links", "favorites"]

    def get_tools(self) -> List[BaseTool]:

        @tool
        def add_bookmark(url: str, title: str = None, notes: str = None) -> str:
            """
            Save a bookmark.

            Args:
                url: The URL to bookmark
                title: Optional title for the bookmark
                notes: Optional notes about the bookmark
            """
            if not self.vectorstore:
                self._initialize_store()
            if not self.vectorstore:
                return "Error: Bookmark system not initialized. Please check your API key configuration."

            try:
                from langchain_core.documents import Document
                content = f"{title or url}\n{notes or ''}\nURL: {url}"
                meta = {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "type": "bookmark",
                    "url": url,
                    "title": title or url
                }
                self.vectorstore.add_documents([Document(page_content=content, metadata=meta)])
                return f"Bookmark saved: {title or url}"
            except Exception as e:
                return f"Failed to save bookmark: {e}"

        @tool
        def list_bookmarks(query: str = None, limit: int = 10) -> str:
            """
            List saved bookmarks, optionally filtered by query.

            Args:
                query: Optional search query for semantic search
                limit: Maximum number of bookmarks to return (default: 10)
            """
            if not self.vectorstore:
                self._initialize_store()
            if not self.vectorstore:
                return "Error: Bookmark system not initialized."

            try:
                collection = self.vectorstore._collection
                
                if query:
                    # Use semantic search
                    docs = self.vectorstore.similarity_search(query, k=limit)
                    result = []
                    for i, doc in enumerate(docs, 1):
                        title = doc.metadata.get("title", "Untitled")
                        url = doc.metadata.get("url", "")
                        notes = doc.page_content
                        result.append(f"{i}. **{title}**\n   URL: {url}\n   Notes: {notes[:150]}")
                    return "\n\n".join(result) if result else f"No bookmarks found matching '{query}'."
                else:
                    # List all
                    data = collection.get(include=["documents", "metadatas"], limit=limit)
                    docs = data.get("documents", [])
                    metas = data.get("metadatas", [])

                    if not docs:
                        return "No bookmarks found."

                    result = []
                    for i, (doc, meta) in enumerate(zip(docs, metas), 1):
                        title = meta.get("title", "Untitled")
                        url = meta.get("url", "")
                        result.append(f"{i}. **{title}**\n   URL: {url}")

                    return "\n\n".join(result)
            except Exception as e:
                return f"Failed to list bookmarks: {e}"

        @tool
        def search_bookmarks(query: str, limit: int = 5) -> str:
            """
            Search bookmarks by semantic similarity.

            Args:
                query: Search query
                limit: Maximum number of results (default: 5)
            """
            if not self.vectorstore:
                self._initialize_store()
            if not self.vectorstore:
                return "Error: Bookmark system not initialized."

            try:
                docs = self.vectorstore.similarity_search(query, k=limit)
                if not docs:
                    return f"No bookmarks found matching '{query}'."

                result = []
                for i, doc in enumerate(docs, 1):
                    title = doc.metadata.get("title", "Untitled")
                    url = doc.metadata.get("url", "")
                    content = doc.page_content[:200]
                    result.append(f"{i}. **{title}**\n   URL: {url}\n   {content}")

                return "\n\n".join(result)
            except Exception as e:
                return f"Failed to search bookmarks: {e}"

        @tool
        def delete_bookmark(url: str) -> str:
            """
            Delete a bookmark by URL.

            Args:
                url: The URL of the bookmark to delete
            """
            if not self.vectorstore:
                self._initialize_store()
            if not self.vectorstore:
                return "Error: Bookmark system not initialized."

            try:
                # Find bookmarks with matching URL
                collection = self.vectorstore._collection
                data = collection.get(include=["metadatas"])
                metas = data.get("metadatas", [])
                
                ids_to_delete = []
                for doc_id, meta in zip(data.get("ids", []), metas):
                    if meta.get("url") == url:
                        ids_to_delete.append(doc_id)
                
                if not ids_to_delete:
                    return f"No bookmark found with URL: {url}"
                
                self.vectorstore.delete(ids=ids_to_delete)
                return f"Deleted {len(ids_to_delete)} bookmark(s) matching URL."
            except Exception as e:
                return f"Failed to delete bookmark: {e}"

        @tool
        def open_bookmark(query: str) -> str:
            """
            Open a bookmark in the browser by searching for it.

            Args:
                query: Search query to find the bookmark
            """
            import webbrowser
            
            if not self.vectorstore:
                self._initialize_store()
            if not self.vectorstore:
                return "Error: Bookmark system not initialized."

            try:
                docs = self.vectorstore.similarity_search(query, k=1)
                if not docs:
                    return f"No bookmark found matching '{query}'."

                url = docs[0].metadata.get("url")
                if url:
                    webbrowser.open(url)
                    return f"Opened {url} in browser"
                else:
                    return "Bookmark found but no URL available."
            except Exception as e:
                return f"Failed to open bookmark: {e}"

        return [add_bookmark, list_bookmarks, search_bookmarks, delete_bookmark, open_bookmark]
