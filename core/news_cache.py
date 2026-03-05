"""
News Cache Management System

Stores and retrieves cached news searches for easy access.
"""

import os
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from core.paths import paths


class NewsCacheEntry:
    """Represents a cached news search."""

    def __init__(
        self,
        query: str,
        news_items: List[Dict[str, Any]],
        timestamp: str = None,
        cache_id: str = None
    ):
        self.query = query
        self.news_items = news_items
        self.timestamp = timestamp or datetime.now().isoformat()
        self.cache_id = cache_id or self._generate_id()

    def _generate_id(self) -> str:
        """Generate a unique ID for this cache entry."""
        return f"news_{int(datetime.now().timestamp())}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "cache_id": self.cache_id,
            "query": self.query,
            "timestamp": self.timestamp,
            "news_items": self.news_items
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NewsCacheEntry":
        """Create from dictionary."""
        return cls(
            query=data["query"],
            news_items=data["news_items"],
            timestamp=data["timestamp"],
            cache_id=data["cache_id"]
        )

    def get_display_title(self) -> str:
        """Get a human-readable title for display."""
        dt = datetime.fromisoformat(self.timestamp)
        time_str = dt.strftime("%b %d, %Y %H:%M")
        return f"\"{self.query}\" ({time_str})"


class NewsCacheManager:
    """Manages cached news searches."""

    def __init__(self):
        self.cache_dir = paths.get_skill_data_dir("news_cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._cache_file = os.path.join(self.cache_dir, "news_searches.json")
        self._cached_entries: List[NewsCacheEntry] = []
        self._load_cache()

    def _load_cache(self):
        """Load cached entries from disk."""
        if os.path.exists(self._cache_file):
            try:
                with open(self._cache_file, "r") as f:
                    data = json.load(f)
                    self._cached_entries = [
                        NewsCacheEntry.from_dict(entry)
                        for entry in data
                    ]
            except Exception:
                self._cached_entries = []

    def _save_cache(self):
        """Save cached entries to disk."""
        try:
            data = [entry.to_dict() for entry in self._cached_entries]
            with open(self._cache_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[dim]Warning: Failed to save news cache: {e}[/dim]")

    def save_search(self, query: str, news_items: List[Dict[str, Any]]) -> str:
        """
        Save a news search to cache.

        Args:
            query: The search query
            news_items: List of news items

        Returns:
            The cache ID of the saved entry
        """
        entry = NewsCacheEntry(query=query, news_items=news_items)
        self._cached_entries.insert(0, entry)  # Add to beginning (most recent first)

        # Keep only the last 50 searches
        if len(self._cached_entries) > 50:
            self._cached_entries = self._cached_entries[:50]

        self._save_cache()
        return entry.cache_id

    def get_all_searches(self) -> List[NewsCacheEntry]:
        """Get all cached searches."""
        return self._cached_entries.copy()

    def get_search(self, cache_id: str) -> Optional[NewsCacheEntry]:
        """Get a specific cached search by ID."""
        for entry in self._cached_entries:
            if entry.cache_id == cache_id:
                return entry
        return None

    def get_most_recent(self) -> Optional[NewsCacheEntry]:
        """Get the most recent cached search."""
        if self._cached_entries:
            return self._cached_entries[0]
        return None

    def delete_search(self, cache_id: str) -> bool:
        """Delete a cached search."""
        for i, entry in enumerate(self._cached_entries):
            if entry.cache_id == cache_id:
                del self._cached_entries[i]
                self._save_cache()
                return True
        return False

    def clear_all(self) -> int:
        """Clear all cached searches. Returns number cleared."""
        count = len(self._cached_entries)
        self._cached_entries = []
        self._save_cache()
        return count


# Global instance
_news_cache_manager: Optional[NewsCacheManager] = None


def get_news_cache_manager() -> NewsCacheManager:
    """Get the global news cache manager instance."""
    global _news_cache_manager
    if _news_cache_manager is None:
        _news_cache_manager = NewsCacheManager()
    return _news_cache_manager
