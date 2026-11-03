"""Local, dependency-free storage for notes.

Notes used to live only in Chroma.  That made every save depend on an
embedding API call, so an exhausted quota (or a missing key) turned a trivial
"save this note" into a 500 error.  Notes are small and few, so they are kept
in a plain JSON file and searched lexically instead:

* saving works with no network, no API key and no embedding credits;
* the file is human-inspectable and easy to back up;
* the old Chroma collection is still read once and imported (see
  ``MemorySkill._migrate_legacy_notes``), so existing notes are not lost.

The store is written atomically and guarded by a re-entrant lock, so the web
server, the CLI and the agent's tool calls can share one process safely.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def _iso(timestamp: Optional[datetime] = None) -> str:
    return (timestamp or datetime.now()).isoformat()


class NoteStore:
    """A tiny JSON-backed note store with atomic writes."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> Dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"version": 1, "legacy_imported": False, "notes": []}
        if not isinstance(raw, dict):
            return {"version": 1, "legacy_imported": False, "notes": []}
        notes = raw.get("notes")
        if not isinstance(notes, list):
            notes = []
        return {
            "version": int(raw.get("version") or 1),
            "legacy_imported": bool(raw.get("legacy_imported")),
            "notes": [note for note in notes if isinstance(note, dict) and note.get("content")],
        }

    def _save(self, state: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(self, content: str, *, note_id: Optional[str] = None, timestamp: Optional[str] = None) -> Dict[str, Any]:
        text = str(content or "").strip()
        if not text:
            raise ValueError("Note content is empty.")
        note = {
            "id": note_id or uuid.uuid4().hex,
            "content": text,
            "timestamp": timestamp or _iso(),
        }
        with self._lock:
            state = self._load()
            state["notes"].append(note)
            self._save(state)
        return dict(note)

    def list(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._lock:
            notes = self._load()["notes"]
        notes = sorted(notes, key=lambda note: str(note.get("timestamp") or ""), reverse=True)
        if limit is not None and limit >= 0:
            notes = notes[:limit]
        return [dict(note) for note in notes]

    def get(self, note_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for note in self._load()["notes"]:
                if note.get("id") == note_id:
                    return dict(note)
        return None

    def update(self, note_id: str, content: str) -> Optional[Dict[str, Any]]:
        text = str(content or "").strip()
        if not text:
            raise ValueError("Note content is empty.")
        with self._lock:
            state = self._load()
            for note in state["notes"]:
                if note.get("id") == note_id:
                    note["content"] = text
                    note["timestamp"] = _iso()
                    self._save(state)
                    return dict(note)
        return None

    def delete(self, note_ids: Iterable[str]) -> int:
        wanted = {str(i) for i in note_ids if i}
        if not wanted:
            return 0
        with self._lock:
            state = self._load()
            kept = [note for note in state["notes"] if note.get("id") not in wanted]
            removed = len(state["notes"]) - len(kept)
            if removed:
                state["notes"] = kept
                self._save(state)
        return removed

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        needle = " ".join(str(query or "").lower().split())
        if not needle:
            return []
        with self._lock:
            notes = self._load()["notes"]
        scored = []
        for index, note in enumerate(notes):
            haystack = str(note.get("content") or "").lower()
            if needle in haystack:
                # Prefer exact phrase matches, then the most recent note.
                scored.append((0, index, note))
                continue
            terms = [t for t in needle.split() if len(t) > 1]
            if terms and all(term in haystack for term in terms):
                scored.append((1, index, note))
        scored.sort(key=lambda item: item[0])
        return [dict(item[2]) for item in scored[: max(0, limit)]]

    # ------------------------------------------------------------------
    # One-off migration from the old Chroma collection
    # ------------------------------------------------------------------

    def legacy_imported(self) -> bool:
        with self._lock:
            return self._load()["legacy_imported"]

    def _merge(self, state: Dict[str, Any], notes: Iterable[Dict[str, Any]]) -> int:
        known = {
            (str(note.get("content") or ""), str(note.get("timestamp") or ""))
            for note in state["notes"]
        }
        added = 0
        for note in notes:
            text = str(note.get("content") or "").strip()
            if not text:
                continue
            stamp = str(note.get("timestamp") or _iso())
            if (text, stamp) in known:
                continue
            state["notes"].append(
                {
                    "id": str(note.get("id") or uuid.uuid4().hex),
                    "content": text,
                    "timestamp": stamp,
                }
            )
            known.add((text, stamp))
            added += 1
        return added

    def merge_notes(self, notes: Iterable[Dict[str, Any]]) -> int:
        """Merge notes from another store; does not mark the legacy migration done."""
        with self._lock:
            state = self._load()
            added = self._merge(state, notes)
            if added:
                self._save(state)
        return added

    def import_notes(self, notes: Iterable[Dict[str, Any]]) -> int:
        """One-off import of the legacy Chroma notes; marks migration as done."""
        with self._lock:
            state = self._load()
            added = self._merge(state, notes)
            state["legacy_imported"] = True
            self._save(state)
        return added

    def mark_legacy_imported(self) -> None:
        with self._lock:
            state = self._load()
            if not state["legacy_imported"]:
                state["legacy_imported"] = True
                self._save(state)
