"""
Diary Skill - Allows keeping diary entries and journaling.
"""
from typing import List, Dict, Any
import datetime
import os
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


class DiarySkill(Skill):
    """Provides diary and journaling capabilities."""

    def __init__(self, skill_root=None):
        super().__init__(skill_root)
        self.vectorstore = None
        self._initialized = False

    def configure(self, config: Dict[str, Any]):
        """Configure the skill and initialize the vector store."""
        super().configure(config)
        self._initialize_store()

    def _initialize_store(self):
        """Initialize the diary vector store if configuration is available."""
        if self._initialized and self.vectorstore is not None:
            return

        self._initialized = False
        api_key = self.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")

        if not api_key or not Chroma:
            return

        try:
            self.embeddings = OpenAIEmbeddings(api_key=api_key, model="text-embedding-ada-002")

            persist_dir = os.path.join(
                os.path.expanduser("~"), ".collig", "data", "diary"
            )
            self.vectorstore = Chroma(
                persist_directory=persist_dir,
                embedding_function=self.embeddings,
                collection_name="user_diary"
            )
            self._initialized = True
        except Exception as e:
            print(f"Failed to initialize diary storage: {e}")

    @property
    def name(self) -> str:
        return "Diary"

    @property
    def description(self) -> str:
        return "Keep diary entries and personal journal"

    @property
    def triggers(self) -> List[str]:
        return ["diary", "journal", "write entry", "daily entry"]

    def get_tools(self) -> List[BaseTool]:

        @tool
        def write_diary_entry(content: str, date: str = None) -> str:
            """
            Write a diary entry.

            Args:
                content: The diary entry content
                date: Optional date (YYYY-MM-DD), defaults to today
            """
            if not self.vectorstore:
                self._initialize_store()
            if not self.vectorstore:
                return "Error: Diary system not initialized."

            try:
                if not date:
                    date = datetime.datetime.now().strftime("%Y-%m-%d")

                doc = Document(
                    page_content=content,
                    metadata={"date": date, "timestamp": datetime.datetime.now().isoformat()}
                )
                self.vectorstore.add_documents([doc])
                return f"Diary entry saved for {date}: {content[:50]}..."
            except Exception as e:
                return f"Failed to save diary entry: {e}"

        @tool
        def read_diary_entry(date: str) -> str:
            """
            Read a diary entry for a specific date.

            Args:
                date: The date to read (YYYY-MM-DD)
            """
            if not self.vectorstore:
                self._initialize_store()
            if not self.vectorstore:
                return "Error: Diary system not initialized."

            try:
                collection = self.vectorstore._collection
                data = collection.get(
                    where={"date": date},
                    include=["documents", "metadatas"]
                )
                docs = data.get("documents", [])
                metas = data.get("metadatas", [])

                if not docs:
                    return f"No diary entry found for {date}."

                entries = []
                for i, (doc, meta) in enumerate(zip(docs, metas), 1):
                    ts = meta.get("timestamp", "")
                    entries.append(f"[{ts}]\n{doc}")

                return "\n\n---\n\n".join(entries)
            except Exception as e:
                return f"Failed to read diary entry: {e}"

        @tool
        def list_diary_entries(start_date: str = None, end_date: str = None) -> str:
            """
            List diary entries within a date range.

            Args:
                start_date: Start date (YYYY-MM-DD), defaults to beginning
                end_date: End date (YYYY-MM-DD), defaults to today
            """
            if not self.vectorstore:
                self._initialize_store()
            if not self.vectorstore:
                return "Error: Diary system not initialized."

            try:
                collection = self.vectorstore._collection
                data = collection.get(include=["documents", "metadatas"])
                docs = data.get("documents", [])
                metas = data.get("metadatas", [])

                if not docs:
                    return "No diary entries found."

                # Filter by date range if specified
                results = []
                for doc, meta in zip(docs, metas):
                    entry_date = meta.get("date", "")
                    if start_date and entry_date < start_date:
                        continue
                    if end_date and entry_date > end_date:
                        continue

                    results.append({
                        "date": entry_date,
                        "timestamp": meta.get("timestamp", ""),
                        "content": doc[:200] + "..." if len(doc) > 200 else doc
                    })

                # Sort by date descending
                results.sort(key=lambda x: x["date"], reverse=True)

                if not results:
                    return "No diary entries found in specified range."

                output = []
                for i, r in enumerate(results, 1):
                    output.append(f"{i}. **{r['date']}** ({r['timestamp']})\n   {r['content']}")

                return "\n\n".join(output)
            except Exception as e:
                return f"Failed to list diary entries: {e}"

        return [write_diary_entry, read_diary_entry, list_diary_entries]
