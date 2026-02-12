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

class MemorySkill(Skill):
    def __init__(self):
        super().__init__()
        self.vectorstore = None
        # Use centralized data directory
        self.persist_directory = paths.get_skill_data_dir("memory_notes")
        self.last_retrieved_ids = [] # To store IDs of listed notes for deletion by index

        # Ensure data directory exists
        # os.makedirs(self.persist_directory, exist_ok=True) # handled by paths

        self._initialize_store()

    @property
    def name(self) -> str:
        return "Memory & Notes"

    @property
    def description(self) -> str:
        return "Stores and retrieves personal notes using a local vector database."

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
                    collection_name="user_memory"
                )
            except Exception as e:
                print(f"Failed to initialize Chroma: {e}")

    @property
    def required_config(self) -> List[str]:
        return ["OPENAI_API_KEY"]

    def get_tools(self) -> List[BaseTool]:

        @tool
        def add_note(content: str) -> str:
            """
            Save a new note, memory, or information to the personal database.
            Args:
                content: The content of the note to save.
            """
            if not self.vectorstore:
                return "Memory system not initialized. Check OPENAI_API_KEY."

            meta = {
                "timestamp": datetime.datetime.now().isoformat(),
                "type": "user_note"
            }
            self.vectorstore.add_documents([Document(page_content=content, metadata=meta)])
            return "✅ Saved to memory."

        @tool
        def list_notes() -> str:
            """
            List the 10 most recent notes.
            """
            if not self.vectorstore:
                return "Memory system not initialized."

            try:
                collection = self.vectorstore._collection
                data = collection.get(limit=100, include=["documents", "metadatas"])

                docs = data.get("documents", [])
                metas = data.get("metadatas", [])
                ids = data.get("ids", [])

                combined = []
                for d, m, i in zip(docs, metas, ids):
                    combined.append({"content": d, "metadata": m, "id": i})

                combined.sort(key=lambda x: x["metadata"].get("timestamp", ""), reverse=True)
                recent = combined[:10]

                self.last_retrieved_ids = [r["id"] for r in recent]

                if not recent:
                    return "You don't have any saved notes yet."

                response_text = "Here are your most recent notes:\n"
                for i, item in enumerate(recent):
                    content = item["content"]
                    ts = item["metadata"].get("timestamp", "")[:16].replace("T", " ")
                    response_text += f"{i+1}. [{ts}] {content}\n"

                return response_text
            except Exception as e:
                return f"❌ Failed to retrieve notes list: {e}"

        @tool
        def search_notes(query: str) -> str:
            """
            Search for information in existing notes by semantic similarity.
            Args:
                query: The search query.
            """
            if not self.vectorstore:
                return "Memory system not initialized."

            results = self.vectorstore.similarity_search(query, k=3)
            if not results:
                return "I couldn't find any relevant notes in your memory."

            response_text = "Here's what I found in your notes:\n"
            for i, doc in enumerate(results):
                snippet = doc.page_content.replace("\n", " ")
                response_text += f"{i+1}. {snippet}\n"

            return response_text

        @tool
        def delete_notes(indices: List[int]) -> str:
            """
            Delete notes by their index number (e.g., [1, 2]) from the most recent 'list_notes' output.
            Args:
                indices: List of integer indices of notes to delete (1-based).
            """
            if not self.vectorstore:
                return "Memory system not initialized."

            if not self.last_retrieved_ids:
                 return "I don't have a recent list of notes to delete from. Please call 'list_notes' first."

            deleted_indices = []
            failed_indices = []
            ids_to_delete = []

            for idx in indices:
                adj_idx = idx - 1
                if 0 <= adj_idx < len(self.last_retrieved_ids):
                    ids_to_delete.append(self.last_retrieved_ids[adj_idx])
                    deleted_indices.append(idx)
                else:
                    failed_indices.append(idx)

            if ids_to_delete:
                try:
                    self.vectorstore.delete(ids=ids_to_delete)
                    response_msg = f"✅ Deleted note(s): {', '.join(map(str, deleted_indices))}."
                    if failed_indices:
                        response_msg += f"\n❌ Could not find note(s): {', '.join(map(str, failed_indices))}."
                    return response_msg
                except Exception as e:
                    return f"❌ Failed to delete notes: {e}"
            else:
                 return f"❌ Invalid note number(s). Please check the list again."

        return [add_note, list_notes, search_notes, delete_notes]
