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


class DiarySkill(Skill):
    def __init__(self):
        super().__init__()
        self.vectorstore = None
        # Use centralized data directory
        self.persist_directory = paths.get_skill_data_dir("diary")
        self.last_retrieved_ids = []  # To store IDs of listed entries for deletion by index

        self._initialize_store()

    @property
    def name(self) -> str:
        return "Diary"

    @property
    def description(self) -> str:
        return "Stores and retrieves personal diary entries with timestamps using a local vector database."

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
                    collection_name="user_diary"
                )
            except Exception as e:
                print(f"Failed to initialize Chroma: {e}")

    @property
    def required_config(self) -> List[str]:
        return ["OPENAI_API_KEY"]

    def configure(self, config: Dict[str, Any]):
        """Configure the skill and reinitialize the vector store if API key becomes available."""
        super().configure(config)
        if not self.vectorstore:
            self._initialize_store()

    def get_tools(self) -> List[BaseTool]:

        @tool
        def create_diary(content: str) -> str:
            """
            Create a new diary entry with the given content. Automatically saves with timestamp.
            Args:
                content: The diary entry content to save.
            """
            if not self.vectorstore:
                return "Diary system not initialized. Check OPENAI_API_KEY."

            meta = {
                "timestamp": datetime.datetime.now().isoformat(),
                "type": "diary_entry"
            }
            self.vectorstore.add_documents([Document(page_content=content, metadata=meta)])
            return "✅ Diary entry saved."

        @tool
        def list_diary_entries(limit: int = 10) -> str:
            """
            List the most recent diary entries (default 10).
            Args:
                limit: Maximum number of entries to return (default 10).
            """
            if not self.vectorstore:
                return "Diary system not initialized."

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
                recent = combined[:limit]

                self.last_retrieved_ids = [r["id"] for r in recent]

                if not recent:
                    return "You don't have any diary entries yet."

                response_text = f"Here are your {len(recent)} most recent diary entries:\n"
                for i, item in enumerate(recent):
                    content = item["content"]
                    ts = item["metadata"].get("timestamp", "")[:16].replace("T", " ")
                    response_text += f"{i+1}. [{ts}] {content}\n"

                return response_text
            except Exception as e:
                return f"❌ Failed to retrieve diary entries: {e}"

        @tool
        def search_diary(query: str) -> str:
            """
            Search for diary entries by semantic similarity.
            Args:
                query: The search query.
            """
            if not self.vectorstore:
                return "Diary system not initialized."

            results = self.vectorstore.similarity_search(query, k=5)
            if not results:
                return "I couldn't find any relevant diary entries."

            response_text = "Here's what I found in your diary:\n"
            for i, doc in enumerate(results):
                snippet = doc.page_content.replace("\n", " ")
                ts = doc.metadata.get("timestamp", "")[:16].replace("T", " ")
                response_text += f"{i+1}. [{ts}] {snippet}\n"

            return response_text

        @tool
        def search_diary_by_date(start_date: str, end_date: Optional[str] = None) -> str:
            """
            Search diary entries by date range.
            Args:
                start_date: Start date in YYYY-MM-DD format.
                end_date: End date in YYYY-MM-DD format (optional, defaults to start_date).
            """
            if not self.vectorstore:
                return "Diary system not initialized."

            try:
                collection = self.vectorstore._collection
                data = collection.get(limit=100, include=["documents", "metadatas"])

                docs = data.get("documents", [])
                metas = data.get("metadatas", [])
                ids = data.get("ids", [])

                # Parse start date
                try:
                    start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
                except ValueError:
                    return "❌ Invalid start_date format. Use YYYY-MM-DD."

                # Parse end date (default to start_date if not provided)
                if end_date:
                    try:
                        end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d")
                    except ValueError:
                        return "❌ Invalid end_date format. Use YYYY-MM-DD."
                else:
                    end_dt = start_dt

                # Add one day to end_dt to include the entire end day
                end_dt = end_dt + datetime.timedelta(days=1)

                filtered = []
                for d, m, i in zip(docs, metas, ids):
                    ts = m.get("timestamp", "")
                    if ts:
                        try:
                            entry_dt = datetime.datetime.fromisoformat(ts)
                            if start_dt <= entry_dt < end_dt:
                                filtered.append({"content": d, "metadata": m, "id": i})
                        except ValueError:
                            continue

                if not filtered:
                    return f"No diary entries found between {start_date} and {end_date or start_date}."

                # Sort by timestamp (newest first)
                filtered.sort(key=lambda x: x["metadata"].get("timestamp", ""), reverse=True)

                response_text = f"Found {len(filtered)} diary entries:\n"
                for i, item in enumerate(filtered):
                    content = item["content"]
                    ts = item["metadata"].get("timestamp", "")[:16].replace("T", " ")
                    response_text += f"{i+1}. [{ts}] {content}\n"

                return response_text
            except Exception as e:
                return f"❌ Failed to search diary by date: {e}"

        @tool
        def delete_diary_entry(indices: List[int]) -> str:
            """
            Delete diary entries by their index number from the most recent list/search output.
            Args:
                indices: List of integer indices of entries to delete (1-based).
            """
            if not self.vectorstore:
                return "Diary system not initialized."

            if not self.last_retrieved_ids:
                return "I don't have a recent list of diary entries to delete from. Please call 'list_diary_entries' or 'search_diary' first."

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
                    response_msg = f"✅ Deleted diary entry(s): {', '.join(map(str, deleted_indices))}."
                    if failed_indices:
                        response_msg += f"\n❌ Could not find entry(s): {', '.join(map(str, failed_indices))}."
                    return response_msg
                except Exception as e:
                    return f"❌ Failed to delete diary entries: {e}"
            else:
                return f"❌ Invalid entry number(s). Please check the list again."

        return [create_diary, list_diary_entries, search_diary, search_diary_by_date, delete_diary_entry]
