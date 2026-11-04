"""Local, dependency-free storage for diary entries.

Diary saves used to require an OpenAI embedding call.  When the account ran out
of credits, a plain "Save" in the Diary page returned HTTP 429/500 and the
dialog stayed open.

Entries are small and personal, so they are now stored in a JSON file and can
be saved with no network, no API key and no embedding credits.  The old Chroma
collection is read once without constructing an embedding client (Chroma can
return stored documents without embeddings) and imported into this store.
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


def _date(timestamp: Optional[datetime] = None) -> str:
    return (timestamp or datetime.now()).strftime("%Y-%m-%d")


class DiaryStore:
    """A tiny JSON-backed diary store with atomic writes."""

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
            return {"version": 1, "legacy_imported": False, "entries": []}
        if not isinstance(raw, dict):
            return {"version": 1, "legacy_imported": False, "entries": []}
        entries = raw.get("entries")
        if not isinstance(entries, list):
            entries = []
        cleaned = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            text = str(entry.get("content") or "").strip()
            if not text:
                continue
            timestamp = str(entry.get("timestamp") or _iso())
            cleaned.append(
                {
                    "id": str(entry.get("id") or uuid.uuid4().hex),
                    "content": text,
                    "date": str(entry.get("date") or timestamp[:10] or _date()),
                    "timestamp": timestamp,
                }
            )
        return {
            "version": int(raw.get("version") or 1),
            "legacy_imported": bool(raw.get("legacy_imported")),
            "entries": cleaned,
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

    def add(
        self,
        content: str,
        *,
        date: Optional[str] = None,
        entry_id: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> Dict[str, Any]:
        text = str(content or "").strip()
        if not text:
            raise ValueError("Diary entry content is empty.")
        stamp = timestamp or _iso()
        entry = {
            "id": entry_id or uuid.uuid4().hex,
            "content": text,
            "date": str(date or stamp[:10] or _date()),
            "timestamp": stamp,
        }
        with self._lock:
            state = self._load()
            state["entries"].append(entry)
            self._save(state)
        return dict(entry)

    def list(
        self,
        limit: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            entries = self._load()["entries"]
        if start_date:
            entries = [entry for entry in entries if str(entry.get("date") or "") >= str(start_date)]
        if end_date:
            entries = [entry for entry in entries if str(entry.get("date") or "") <= str(end_date)]
        entries.sort(key=lambda entry: str(entry.get("timestamp") or ""), reverse=True)
        if limit is not None and limit >= 0:
            entries = entries[:limit]
        return [dict(entry) for entry in entries]

    def get(self, entry_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for entry in self._load()["entries"]:
                if entry.get("id") == entry_id:
                    return dict(entry)
        return None

    def update(self, entry_id: str, content: str, *, date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        text = str(content or "").strip()
        if not text:
            raise ValueError("Diary entry content is empty.")
        with self._lock:
            state = self._load()
            for entry in state["entries"]:
                if entry.get("id") == entry_id:
                    entry["content"] = text
                    entry["timestamp"] = _iso()
                    entry["date"] = str(date or entry["timestamp"][:10])
                    self._save(state)
                    return dict(entry)
        return None

    def delete(self, entry_ids: Iterable[str]) -> int:
        wanted = {str(entry_id) for entry_id in entry_ids if entry_id}
        if not wanted:
            return 0
        with self._lock:
            state = self._load()
            kept = [entry for entry in state["entries"] if entry.get("id") not in wanted]
            removed = len(state["entries"]) - len(kept)
            if removed:
                state["entries"] = kept
                self._save(state)
        return removed

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        needle = " ".join(str(query or "").lower().split())
        if not needle:
            return []
        with self._lock:
            entries = self._load()["entries"]
        scored = []
        for index, entry in enumerate(entries):
            haystack = (str(entry.get("content") or "") + " " + str(entry.get("date") or "")).lower()
            if needle in haystack:
                scored.append((0, index, entry))
                continue
            terms = [term for term in needle.split() if len(term) > 1]
            if terms and all(term in haystack for term in terms):
                scored.append((1, index, entry))
        scored.sort(key=lambda item: item[0])
        return [dict(item[2]) for item in scored[: max(0, limit)]]

    # ------------------------------------------------------------------
    # Legacy Chroma import
    # ------------------------------------------------------------------

    def legacy_imported(self) -> bool:
        with self._lock:
            return self._load()["legacy_imported"]

    def _merge(self, state: Dict[str, Any], entries: Iterable[Dict[str, Any]]) -> int:
        known = {(str(entry.get("content") or ""), str(entry.get("timestamp") or "")) for entry in state["entries"]}
        added = 0
        for entry in entries:
            text = str(entry.get("content") or "").strip()
            if not text:
                continue
            stamp = str(entry.get("timestamp") or _iso())
            if (text, stamp) in known:
                continue
            state["entries"].append(
                {
                    "id": str(entry.get("id") or uuid.uuid4().hex),
                    "content": text,
                    "date": str(entry.get("date") or stamp[:10] or _date()),
                    "timestamp": stamp,
                }
            )
            known.add((text, stamp))
            added += 1
        return added

    def import_entries(self, entries: Iterable[Dict[str, Any]]) -> int:
        with self._lock:
            state = self._load()
            added = self._merge(state, entries)
            state["legacy_imported"] = True
            self._save(state)
        return added

    def mark_legacy_imported(self) -> None:
        with self._lock:
            state = self._load()
            if not state["legacy_imported"]:
                state["legacy_imported"] = True
                self._save(state)
