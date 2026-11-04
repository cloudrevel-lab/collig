"""
Diary Skill - local journaling that does not depend on an embedding provider.

Entries are stored in a small JSON file (see skills/diary/store.py).  The old
Chroma collection is read once without constructing OpenAIEmbeddings and
imported, so existing diary entries remain visible even when the embedding
account is out of credits or no OpenAI key is configured.
"""

from __future__ import annotations

import datetime
import logging
import os
from typing import Any, Dict, List, Optional

from langchain_core.tools import BaseTool, tool

from skills.base import Skill
from skills.diary.store import DiaryStore

logger = logging.getLogger(__name__)


def _default_diary_path() -> str:
    try:
        from core.paths import paths

        folder = paths.get_skill_data_dir("diary")
    except Exception:
        folder = os.path.join(os.path.expanduser("~"), ".collig", "data", "diary")
    return os.path.join(folder, "diary.json")


class DiarySkill(Skill):
    """Provides diary and journaling capabilities."""

    def __init__(self, skill_root=None, entry_store_path: Optional[str] = None):
        super().__init__(skill_root)
        self.vectorstore = None
        self._entries: Optional[DiaryStore] = None
        self._entry_store_path = entry_store_path
        self._initialized = False
        self._migration_enabled = entry_store_path is None

    def configure(self, config: Dict[str, Any]):
        super().configure(config)
        self._initialized = False
        self._entry_store()
        self._initialize_store()

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def _entry_store(self) -> DiaryStore:
        if self._entries is None:
            self._entries = DiaryStore(self._entry_store_path or _default_diary_path())
        return self._entries

    def store_entry(self, content: str, date: Optional[str] = None) -> Dict[str, Any]:
        return self._entry_store().add(content, date=date)

    def recent_entries(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        return self._entry_store().list(limit=limit)

    def list_entries(
        self,
        limit: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return self._entry_store().list(limit=limit, start_date=start_date, end_date=end_date)

    def get_entry(self, entry_id: str) -> Optional[Dict[str, Any]]:
        return self._entry_store().get(entry_id)

    def edit_entry(self, entry_id: str, content: str, date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self._entry_store().update(entry_id, content, date=date)

    def remove_entries(self, entry_ids: List[str]) -> int:
        return self._entry_store().delete(entry_ids)

    def search_entries(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        return self._entry_store().search(query, limit=limit)

    def _initialize_store(self) -> None:
        """Import the legacy Chroma diary once, without needing embeddings."""
        if self._initialized:
            return
        self._initialized = True
        store = self._entry_store()
        if not self._migration_enabled or store.legacy_imported():
            return
        entries = self._legacy_chroma_entries()
        if entries is None:
            # chromadb is unavailable; retry on a later configure, but never
            # block normal JSON saves.
            self._initialized = False
            return
        try:
            imported = store.import_entries(entries)
            if imported:
                logger.info("Imported %s legacy diary entries from Chroma", imported)
        except Exception:
            logger.warning("Could not import legacy diary entries", exc_info=True)
            self._initialized = False

    def _legacy_chroma_entries(self) -> Optional[List[Dict[str, Any]]]:
        persist_dir = os.path.dirname(_default_diary_path())
        if not os.path.isdir(persist_dir):
            return []
        try:
            import chromadb
        except ImportError:
            return None
        try:
            client = chromadb.PersistentClient(path=persist_dir)
            collection = client.get_or_create_collection("user_diary")
            data = collection.get(include=["documents", "metadatas"])
        except Exception:
            logger.warning("Could not read legacy diary Chroma collection", exc_info=True)
            return None
        entries = []
        for doc, meta, entry_id in zip(
            data.get("documents", []),
            data.get("metadatas", []),
            data.get("ids", []),
        ):
            text = str(doc or "").strip()
            if not text:
                continue
            meta = meta or {}
            timestamp = str(meta.get("timestamp") or datetime.datetime.now().isoformat())
            entries.append(
                {
                    "id": str(entry_id) if entry_id else None,
                    "content": text,
                    "date": str(meta.get("date") or timestamp[:10]),
                    "timestamp": timestamp,
                }
            )
        return entries

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
            try:
                entry = self.store_entry(content, date=date)
            except ValueError:
                return "Failed to save diary entry: the entry is empty."
            except Exception as exc:
                return f"Failed to save diary entry: {exc}"
            return f"Diary entry saved for {entry['date']}: {str(content)[:50]}..."

        @tool
        def read_diary_entry(date: str) -> str:
            """
            Read a diary entry for a specific date.

            Args:
                date: The date to read (YYYY-MM-DD)
            """
            try:
                entries = self.list_entries(start_date=date, end_date=date)
                if not entries:
                    return f"No diary entry found for {date}."
                blocks = [f"[{entry.get('timestamp', '')}]\n{entry.get('content', '')}" for entry in entries]
                return "\n\n---\n\n".join(blocks)
            except Exception as exc:
                return f"Failed to read diary entry: {exc}"

        @tool
        def list_diary_entries(start_date: str = None, end_date: str = None) -> str:
            """
            List diary entries within a date range.

            Args:
                start_date: Start date (YYYY-MM-DD), defaults to beginning
                end_date: End date (YYYY-MM-DD), defaults to today
            """
            try:
                entries = self.list_entries(start_date=start_date, end_date=end_date)
                if not entries:
                    return "No diary entries found."
                output = []
                for index, entry in enumerate(entries, 1):
                    content = str(entry.get("content") or "")
                    preview = content[:200] + "..." if len(content) > 200 else content
                    output.append(f"{index}. **{entry.get('date', '')}** ({entry.get('timestamp', '')})\n   {preview}")
                return "\n\n".join(output)
            except Exception as exc:
                return f"Failed to list diary entries: {exc}"

        return [write_diary_entry, read_diary_entry, list_diary_entries]
