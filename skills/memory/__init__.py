"""
Memory Skill - Provides memory and context management for the agent.

Implements note-taking functionality using vector embeddings for semantic search.
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


class MemorySkill(Skill):
    """Provides memory and note-taking capabilities."""

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

                persist_dir = self.persist_directory or os.path.join(
                    os.path.expanduser("~"), ".collig", "data", "memory_notes"
                )
                self.vectorstore = Chroma(
                    persist_directory=persist_dir,
                    embedding_function=self.embeddings,
                    collection_name="user_memory"
                )
                self._initialized = True
            except Exception as e:
                print(f"Failed to initialize Chroma for memory: {e}")

    @property
    def name(self) -> str:
        return "Memory & Notes"

    @property
    def description(self) -> str:
        return "Save, search, and manage notes and memories"

    @property
    def triggers(self) -> List[str]:
        return ["note", "remember", "save note", "my notes", "search notes", "memory"]

    def get_tools(self) -> List[BaseTool]:

        @tool
        def add_note(content: str) -> str:
            """
            Add a new note to memory.

            Args:
                content: The note content to save
            """
            if not self.vectorstore:
                self._initialize_store()
            if not self.vectorstore:
                return "Error: Memory system not initialized. Please check your API key configuration."

            try:
                from langchain_core.documents import Document
                meta = {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "type": "note"
                }
                self.vectorstore.add_documents([Document(page_content=content, metadata=meta)])
                return "Note saved successfully."
            except Exception as e:
                return f"Failed to save note: {e}"

        @tool
        def list_notes(limit: int = 10) -> str:
            """
            List recent notes.

            Args:
                limit: Maximum number of notes to return (default: 10)
            """
            if not self.vectorstore:
                self._initialize_store()
            if not self.vectorstore:
                return "Error: Memory system not initialized."

            try:
                collection = self.vectorstore._collection
                data = collection.get(include=["documents", "metadatas"], limit=limit)
                docs = data.get("documents", [])
                metas = data.get("metadatas", [])

                if not docs:
                    return "No notes found."

                result = []
                for i, (doc, meta) in enumerate(zip(docs, metas), 1):
                    timestamp = meta.get("timestamp", "Unknown")
                    result.append(f"{i}. [{timestamp}] {doc[:200]}")

                return "\n\n".join(result)
            except Exception as e:
                return f"Failed to list notes: {e}"

        @tool
        def search_notes(query: str, limit: int = 5) -> str:
            """
            Search notes by semantic similarity.

            Args:
                query: Search query
                limit: Maximum number of results (default: 5)
            """
            if not self.vectorstore:
                self._initialize_store()
            if not self.vectorstore:
                return "Error: Memory system not initialized."

            try:
                docs = self.vectorstore.similarity_search(query, k=limit)
                if not docs:
                    return f"No notes found matching '{query}'."

                result = []
                for i, doc in enumerate(docs, 1):
                    content = doc.page_content[:200]
                    result.append(f"{i}. {content}")

                return "\n\n".join(result)
            except Exception as e:
                return f"Failed to search notes: {e}"

        @tool
        def delete_notes(note_ids: List[str]) -> str:
            """
            Delete notes by their IDs.

            Args:
                note_ids: List of note IDs to delete
            """
            if not self.vectorstore:
                self._initialize_store()
            if not self.vectorstore:
                return "Error: Memory system not initialized."

            try:
                self.vectorstore.delete(ids=note_ids)
                return f"Deleted {len(note_ids)} note(s)."
            except Exception as e:
                return f"Failed to delete notes: {e}"

        return [add_note, list_notes, search_notes, delete_notes]
