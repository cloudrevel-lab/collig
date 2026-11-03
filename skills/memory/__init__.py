"""
Memory Skill - Provides memory and context management for the agent.

Notes are stored in a small local JSON file (see ``skills/memory/store.py``)
instead of only in Chroma.  Saving a note must never depend on an embedding
API call: an exhausted quota or a missing key should not turn "save this
note" into an error.  The old Chroma collection is imported once, on the
first run after the switch, so existing notes remain visible.
"""
import logging
import os
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool, BaseTool

from skills.base import Skill
from skills.memory.store import NoteStore

logger = logging.getLogger(__name__)

# Heavy vector-store dependencies (langchain_chroma pulls in chromadb, ~0.6s)
# are imported lazily via ``_load_vectorstore_deps`` and are only needed to
# import the legacy Chroma notes once.  New notes never need them.
Chroma = None
OpenAIEmbeddings = None
Document = None


def _load_vectorstore_deps():
    """Import Chroma/OpenAIEmbeddings/Document on first use. Returns True on success."""
    global Chroma, OpenAIEmbeddings, Document
    if Chroma is not None:
        return True
    try:
        from langchain_openai import OpenAIEmbeddings as _OE
        from langchain_chroma import Chroma as _C
        from langchain_core.documents import Document as _D
        OpenAIEmbeddings, Chroma, Document = _OE, _C, _D
        return True
    except ImportError:
        return False


def _default_notes_path() -> str:
    try:
        from core.paths import paths

        folder = paths.get_skill_data_dir("memory_notes")
    except Exception:
        folder = os.path.join(os.path.expanduser("~"), ".collig", "data", "memory_notes")
    return os.path.join(folder, "notes.json")


def note_warning(content: str) -> str:
    """A non-blocking warning when a note looks like it holds a secret.

    The user may deliberately keep passwords in notes.  We never refuse the
    save; we only tell them it is stored as plain text.
    """
    try:
        from core.user_memory import looks_sensitive
    except Exception:
        return ""
    if not looks_sensitive(content):
        return ""
    return (
        "Warning: this note looks like it contains a password or other secret. "
        "It was saved anyway, in plain text."
    )


class MemorySkill(Skill):
    """Provides memory and note-taking capabilities."""

    def __init__(self, skill_root=None, note_store_path: Optional[str] = None):
        super().__init__(skill_root)
        self.vectorstore = None
        self.persist_directory = None
        self.embeddings = None
        self._initialized = False
        self._notes: Optional[NoteStore] = None
        self._note_store_path = note_store_path
        # An explicitly injected store is already the source of truth (tests,
        # alternate profiles); don't go looking for the legacy Chroma files.
        self._migration_enabled = note_store_path is None

    def configure(self, config: Dict[str, Any]):
        """
        Configure the skill and initialize the note store.
        This is called after the skill is registered and config is available.
        """
        super().configure(config)
        self._initialized = False
        self._note_store()
        self._initialize_store()

    # ------------------------------------------------------------------
    # Note storage
    # ------------------------------------------------------------------

    def _note_store(self) -> NoteStore:
        if self._notes is None:
            self._notes = NoteStore(self._note_store_path or _default_notes_path())
        return self._notes

    def store_note(self, content: str) -> Dict[str, Any]:
        """Save a note and return ``{"note": ..., "warning": ...}``."""
        note = self._note_store().add(content)
        return {"note": note, "warning": note_warning(note["content"])}

    def recent_notes(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        return self._note_store().list(limit=limit)

    def edit_note(self, note_id: str, content: str) -> Optional[Dict[str, Any]]:
        return self._note_store().update(note_id, content)

    def remove_notes(self, note_ids: List[str]) -> int:
        return self._note_store().delete(note_ids)

    def _initialize_store(self):
        """Import the legacy Chroma notes once, if they have not been imported.

        New saves do not touch Chroma, so a missing key or exhausted embedding
        quota cannot break note saving.
        """
        if self._initialized:
            return
        self._initialized = True
        store = self._note_store()
        if not self._migration_enabled or store.legacy_imported():
            return

        vectorstore = self._build_vectorstore()
        if vectorstore is None:
            # No embedding provider configured yet; retry on the next configure.
            self._initialized = False
            return
        try:
            data = vectorstore._collection.get(include=["documents", "metadatas"])
            entries = []
            for doc, meta, note_id in zip(
                data.get("documents", []),
                data.get("metadatas", []),
                data.get("ids", []),
            ):
                entries.append(
                    {
                        "id": note_id,
                        "content": doc,
                        "timestamp": (meta or {}).get("timestamp") or "",
                    }
                )
            imported = store.import_notes(entries)
            if imported:
                logger.info("Imported %s legacy note(s) from Chroma", imported)
        except Exception:
            logger.warning("Could not import legacy notes from Chroma", exc_info=True)
            self._initialized = False

    def _build_vectorstore(self):
        """Build the legacy Chroma handle. Returns None when unavailable."""
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
                "international": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            }
            base_url = endpoints.get(endpoint_region, endpoints["china"])
            model_name = "text-embedding-v2"
        else:
            api_key = self.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")

        if not api_key:
            return None

        if not _load_vectorstore_deps():
            return None

        try:
            if base_url:
                self.embeddings = OpenAIEmbeddings(api_key=api_key, base_url=base_url, model=model_name)
            else:
                self.embeddings = OpenAIEmbeddings(api_key=api_key, model=model_name)

            persist_dir = self.persist_directory or os.path.dirname(_default_notes_path())
            self.vectorstore = Chroma(
                persist_directory=persist_dir,
                embedding_function=self.embeddings,
                collection_name="user_memory",
            )
            return self.vectorstore
        except Exception as e:
            print(f"Failed to initialize Chroma for memory: {e}")
            return None

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

            The note is stored exactly as written, in plain text. Passwords
            and other secrets are allowed: the user is warned, but the save
            is never blocked.

            Args:
                content: The note content to save
            """
            try:
                result = self.store_note(content)
            except ValueError:
                return "Failed to save note: the note is empty."
            except Exception as e:
                return f"Failed to save note: {e}"
            message = "Note saved successfully."
            if result.get("warning"):
                message += " " + result["warning"]
            return message

        @tool
        def list_notes(limit: int = 10) -> str:
            """
            List recent notes.

            Args:
                limit: Maximum number of notes to return (default: 10)
            """
            try:
                notes = self.recent_notes(limit=limit)
                if not notes:
                    return "No notes found."

                result = []
                for i, note in enumerate(notes, 1):
                    timestamp = note.get("timestamp", "Unknown")
                    result.append(f"{i}. [{timestamp}] {note['content'][:200]}")

                return "\n\n".join(result)
            except Exception as e:
                return f"Failed to list notes: {e}"

        @tool
        def search_notes(query: str, limit: int = 5) -> str:
            """
            Search notes by keyword.

            Args:
                query: Search query
                limit: Maximum number of results (default: 5)
            """
            try:
                notes = self._note_store().search(query, limit=limit)
                if not notes:
                    return f"No notes found matching '{query}'."

                result = []
                for i, note in enumerate(notes, 1):
                    result.append(f"{i}. {note['content'][:200]}")

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
            try:
                removed = self.remove_notes(note_ids)
                return f"Deleted {removed} note(s)."
            except Exception as e:
                return f"Failed to delete notes: {e}"

        return [add_note, list_notes, search_notes, delete_notes]
