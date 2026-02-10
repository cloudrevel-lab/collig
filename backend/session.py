import json
import os
import uuid
from typing import List, Dict, Optional
from datetime import datetime

class SessionManager:
    def __init__(self, sessions_dir: str = "sessions"):
        self.sessions_dir = sessions_dir
        os.makedirs(self.sessions_dir, exist_ok=True)

    def _get_session_path(self, session_id: str) -> str:
        return os.path.join(self.sessions_dir, f"{session_id}.json")

    def create_session(self) -> str:
        """Creates a new session and returns its ID."""
        session_id = str(uuid.uuid4())
        session_data = {
            "id": session_id,
            "created_at": datetime.now().isoformat(),
            "messages": []
        }
        self.save_session(session_id, session_data)
        return session_id

    def load_session(self, session_id: str) -> Optional[Dict]:
        """Loads a session by ID."""
        path = self._get_session_path(session_id)
        if not os.path.exists(path):
            return None
        
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading session {session_id}: {e}")
            return None

    def save_session(self, session_id: str, data: Dict):
        """Saves session data."""
        path = self._get_session_path(session_id)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def add_message(self, session_id: str, role: str, content: str):
        """Adds a message to the session history."""
        session = self.load_session(session_id)
        if not session:
            # If session doesn't exist, recreate it (or handle error)
            # For robustness, we'll re-initialize the structure
            session = {
                "id": session_id,
                "created_at": datetime.now().isoformat(),
                "messages": []
            }
        
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        session["messages"].append(message)
        self.save_session(session_id, session)

    def get_history(self, session_id: str) -> List[Dict]:
        """Returns the message history for a session."""
        session = self.load_session(session_id)
        return session.get("messages", []) if session else []
