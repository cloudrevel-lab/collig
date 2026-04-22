from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import os
import sys
import datetime

# Add parent directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.agent import agent

load_dotenv()

# Configure skills with API keys (same as CLI does)
import json
try:
    from core.paths import paths as _paths
    with open(_paths.global_config_file, "r") as f:
        _config = json.load(f)
except Exception:
    _config = {}

# Merge env vars into config for skills that need them
for var in ["OPENAI_API_KEY", "DEEPSEEK_API_KEY"]:
    if var not in _config and os.getenv(var):
        _config[var] = os.getenv(var)

agent.skill_manager.configure(_config)
for skill in agent.skill_manager.skills:
    skill.configure(_config)

app = FastAPI(title="Collig API", version="0.1.0")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Pydantic Models ───────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str
    action: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

class BookmarkCreate(BaseModel):
    url: str
    description: str = ""
    tags: str = ""

class BookmarkUpdate(BaseModel):
    url: str | None = None
    description: str | None = None
    tags: str | None = None

class NoteCreate(BaseModel):
    content: str

class NoteUpdate(BaseModel):
    content: str | None = None

class DiaryEntryCreate(BaseModel):
    content: str

class DiaryEntryUpdate(BaseModel):
    content: str | None = None


# ─── Helper: get skill instances ───────────────────────────────────────────────

def _get_bookmark_skill():
    """Find the BookmarkSkill from the agent's registered skills."""
    for skill in agent.skill_manager.skills:
        if skill.name == "Bookmarks":
            return skill
    return None

def _get_memory_skill():
    """Find the MemorySkill from the agent's registered skills."""
    for skill in agent.skill_manager.skills:
        if skill.name == "Memory & Notes":
            return skill
    return None

def _get_diary_skill():
    """Find the DiarySkill from the agent's registered skills."""
    for skill in agent.skill_manager.skills:
        if skill.name == "Diary":
            return skill
    return None

def _get_all_bookmarks():
    """Retrieve all bookmarks from ChromaDB."""
    skill = _get_bookmark_skill()
    if not skill or not skill.vectorstore:
        return []
    try:
        collection = skill.vectorstore._collection
        data = collection.get(include=["documents", "metadatas"])
        docs = data.get("documents", [])
        metas = data.get("metadatas", [])
        ids = data.get("ids", [])
        results = []
        for d, m, i in zip(docs, metas, ids):
            # Parse description from content
            desc = ""
            for line in d.split('\n'):
                if line.startswith("Description:"):
                    desc = line.replace("Description:", "").strip()
                    break
            results.append({
                "id": i,
                "url": m.get("url", ""),
                "description": desc,
                "tags": m.get("tags", ""),
                "timestamp": m.get("timestamp", ""),
            })
        # Sort by timestamp desc
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return results
    except Exception as e:
        return []

def _get_all_notes():
    """Retrieve all notes from ChromaDB."""
    skill = _get_memory_skill()
    if not skill or not skill.vectorstore:
        return []
    try:
        collection = skill.vectorstore._collection
        data = collection.get(include=["documents", "metadatas"])
        docs = data.get("documents", [])
        metas = data.get("metadatas", [])
        ids = data.get("ids", [])
        results = []
        for d, m, i in zip(docs, metas, ids):
            results.append({
                "id": i,
                "content": d,
                "timestamp": m.get("timestamp", ""),
            })
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return results
    except Exception as e:
        return []

def _get_all_diary_entries():
    """Retrieve all diary entries from ChromaDB."""
    skill = _get_diary_skill()
    if not skill or not skill.vectorstore:
        return []
    try:
        collection = skill.vectorstore._collection
        data = collection.get(include=["documents", "metadatas"])
        docs = data.get("documents", [])
        metas = data.get("metadatas", [])
        ids = data.get("ids", [])
        results = []
        for d, m, i in zip(docs, metas, ids):
            results.append({
                "id": i,
                "content": d,
                "timestamp": m.get("timestamp", ""),
            })
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return results
    except Exception as e:
        return []


# ─── Chat ──────────────────────────────────────────────────────────────────────

@app.get("/")
def read_root():
    return {"message": "Welcome to Collig Co-worker AI API"}

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    result = agent.process_message(request.message)
    return ChatResponse(
        response=result["response"],
        action=result["action"],
        prompt_tokens=result.get("prompt_tokens"),
        completion_tokens=result.get("completion_tokens"),
        total_tokens=result.get("total_tokens")
    )


# ─── Bookmarks API ─────────────────────────────────────────────────────────────

@app.get("/api/bookmarks")
def list_bookmarks():
    """List all bookmarks."""
    try:
        bookmarks = _get_all_bookmarks()
        return {"bookmarks": bookmarks, "total": len(bookmarks)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/bookmarks", status_code=201)
def create_bookmark(bm: BookmarkCreate):
    """Create a new bookmark."""
    skill = _get_bookmark_skill()
    if not skill or not skill.vectorstore:
        raise HTTPException(status_code=503, detail="Bookmark system not initialized. Check OPENAI_API_KEY.")
    try:
        from langchain_core.documents import Document
        meta = {
            "url": bm.url,
            "timestamp": datetime.datetime.now().isoformat(),
            "tags": bm.tags,
            "type": "user_bookmark"
        }
        search_content = f"URL: {bm.url}\nDescription: {bm.description}\nTags: {bm.tags}"
        skill.vectorstore.add_documents([Document(page_content=search_content, metadata=meta)])
        return {"message": "Bookmark created", "url": bm.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/bookmarks/{bookmark_id}")
def delete_bookmark(bookmark_id: str):
    """Delete a bookmark by ID."""
    skill = _get_bookmark_skill()
    if not skill or not skill.vectorstore:
        raise HTTPException(status_code=503, detail="Bookmark system not initialized.")
    try:
        skill.vectorstore.delete(ids=[bookmark_id])
        return {"message": "Bookmark deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/bookmarks/{bookmark_id}")
def update_bookmark(bookmark_id: str, bm: BookmarkUpdate):
    """Update a bookmark (delete + re-create with new data)."""
    skill = _get_bookmark_skill()
    if not skill or not skill.vectorstore:
        raise HTTPException(status_code=503, detail="Bookmark system not initialized.")
    try:
        # Get existing
        existing = skill.vectorstore._collection.get(ids=[bookmark_id], include=["documents", "metadatas"])
        if not existing.get("ids"):
            raise HTTPException(status_code=404, detail="Bookmark not found")

        old_content = existing["documents"][0]
        old_meta = existing["metadatas"][0]

        # Apply updates
        new_url = bm.url if bm.url is not None else old_meta.get("url", "")
        new_tags = bm.tags if bm.tags is not None else old_meta.get("tags", "")

        # Parse old description
        old_desc = ""
        for line in old_content.split('\n'):
            if line.startswith("Description:"):
                old_desc = line.replace("Description:", "").strip()
                break
        new_desc = bm.description if bm.description is not None else old_desc

        # Delete old, create new
        skill.vectorstore.delete(ids=[bookmark_id])
        from langchain_core.documents import Document
        meta = {"url": new_url, "timestamp": old_meta.get("timestamp", datetime.datetime.now().isoformat()), "tags": new_tags, "type": "user_bookmark"}
        search_content = f"URL: {new_url}\nDescription: {new_desc}\nTags: {new_tags}"
        skill.vectorstore.add_documents([Document(page_content=search_content, metadata=meta)])
        return {"message": "Bookmark updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Notes API ──────────────────────────────────────────────────────────────────

@app.get("/api/notes")
def list_notes():
    """List all notes."""
    try:
        notes = _get_all_notes()
        return {"notes": notes, "total": len(notes)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/notes", status_code=201)
def create_note(note: NoteCreate):
    """Create a new note."""
    skill = _get_memory_skill()
    if not skill or not skill.vectorstore:
        raise HTTPException(status_code=503, detail="Memory system not initialized. Check OPENAI_API_KEY.")
    try:
        from langchain_core.documents import Document
        meta = {"timestamp": datetime.datetime.now().isoformat(), "type": "user_note"}
        skill.vectorstore.add_documents([Document(page_content=note.content, metadata=meta)])
        return {"message": "Note created"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/notes/{note_id}")
def delete_note(note_id: str):
    """Delete a note by ID."""
    skill = _get_memory_skill()
    if not skill or not skill.vectorstore:
        raise HTTPException(status_code=503, detail="Memory system not initialized.")
    try:
        skill.vectorstore.delete(ids=[note_id])
        return {"message": "Note deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/notes/{note_id}")
def update_note(note_id: str, note: NoteUpdate):
    """Update a note."""
    skill = _get_memory_skill()
    if not skill or not skill.vectorstore:
        raise HTTPException(status_code=503, detail="Memory system not initialized.")
    try:
        existing = skill.vectorstore._collection.get(ids=[note_id], include=["documents", "metadatas"])
        if not existing.get("ids"):
            raise HTTPException(status_code=404, detail="Note not found")

        old_content = existing["documents"][0]
        old_meta = existing["metadatas"][0]
        new_content = note.content if note.content is not None else old_content

        skill.vectorstore.delete(ids=[note_id])
        from langchain_core.documents import Document
        meta = {"timestamp": old_meta.get("timestamp", datetime.datetime.now().isoformat()), "type": "user_note"}
        skill.vectorstore.add_documents([Document(page_content=new_content, metadata=meta)])
        return {"message": "Note updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Diary API ──────────────────────────────────────────────────────────────────

@app.get("/api/diary")
def list_diary():
    """List all diary entries."""
    try:
        entries = _get_all_diary_entries()
        return {"entries": entries, "total": len(entries)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/diary", status_code=201)
def create_diary_entry(entry: DiaryEntryCreate):
    """Create a new diary entry."""
    skill = _get_diary_skill()
    if not skill or not skill.vectorstore:
        raise HTTPException(status_code=503, detail="Diary system not initialized. Check OPENAI_API_KEY.")
    try:
        from langchain_core.documents import Document
        meta = {"timestamp": datetime.datetime.now().isoformat(), "type": "diary_entry"}
        skill.vectorstore.add_documents([Document(page_content=entry.content, metadata=meta)])
        return {"message": "Diary entry created"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/diary/{entry_id}")
def delete_diary_entry(entry_id: str):
    """Delete a diary entry by ID."""
    skill = _get_diary_skill()
    if not skill or not skill.vectorstore:
        raise HTTPException(status_code=503, detail="Diary system not initialized.")
    try:
        skill.vectorstore.delete(ids=[entry_id])
        return {"message": "Diary entry deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/diary/{entry_id}")
def update_diary_entry(entry_id: str, entry: DiaryEntryUpdate):
    """Update a diary entry."""
    skill = _get_diary_skill()
    if not skill or not skill.vectorstore:
        raise HTTPException(status_code=503, detail="Diary system not initialized.")
    try:
        existing = skill.vectorstore._collection.get(ids=[entry_id], include=["documents", "metadatas"])
        if not existing.get("ids"):
            raise HTTPException(status_code=404, detail="Diary entry not found")

        old_content = existing["documents"][0]
        old_meta = existing["metadatas"][0]
        new_content = entry.content if entry.content is not None else old_content

        skill.vectorstore.delete(ids=[entry_id])
        from langchain_core.documents import Document
        meta = {"timestamp": old_meta.get("timestamp", datetime.datetime.now().isoformat()), "type": "diary_entry"}
        skill.vectorstore.add_documents([Document(page_content=new_content, metadata=meta)])
        return {"message": "Diary entry updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Sessions API ──────────────────────────────────────────────────────────────

@app.get("/api/sessions")
def list_sessions():
    """List all chat sessions with summary info."""
    try:
        from core.paths import paths as _paths
        sessions_dir = _paths.sessions_dir
        if not os.path.exists(sessions_dir):
            return {"sessions": [], "total": 0}

        sessions = []
        for fname in os.listdir(sessions_dir):
            if not fname.endswith(".json") or fname.endswith("_stats.json"):
                continue
            fpath = os.path.join(sessions_dir, fname)
            try:
                with open(fpath, "r") as f:
                    data = json.load(f)
                msgs = data.get("messages", [])
                # Get first user message as preview
                preview = ""
                for m in msgs:
                    if m.get("role") == "user":
                        preview = m.get("content", "")[:100]
                        break
                # Count messages
                user_count = sum(1 for m in msgs if m.get("role") == "user")
                ai_count = sum(1 for m in msgs if m.get("role") == "ai")

                sessions.append({
                    "id": data.get("id", fname.replace(".json", "")),
                    "created_at": data.get("created_at", ""),
                    "message_count": len(msgs),
                    "user_messages": user_count,
                    "ai_messages": ai_count,
                    "preview": preview,
                    "last_activity": msgs[-1].get("timestamp", data.get("created_at", "")) if msgs else data.get("created_at", ""),
                })
            except Exception:
                continue

        # Sort by last_activity descending
        sessions.sort(key=lambda x: x.get("last_activity", ""), reverse=True)
        return {"sessions": sessions, "total": len(sessions)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    """Get full session details including all messages."""
    try:
        from core.paths import paths as _paths
        fpath = os.path.join(_paths.sessions_dir, f"{session_id}.json")
        if not os.path.exists(fpath):
            raise HTTPException(status_code=404, detail="Session not found")
        with open(fpath, "r") as f:
            data = json.load(f)
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    """Delete a chat session and its stats."""
    try:
        from core.paths import paths as _paths
        # Delete session file
        fpath = os.path.join(_paths.sessions_dir, f"{session_id}.json")
        if os.path.exists(fpath):
            os.remove(fpath)
        # Delete stats file if exists
        stats_path = os.path.join(_paths.sessions_dir, f"{session_id}_stats.json")
        if os.path.exists(stats_path):
            os.remove(stats_path)
        return {"message": "Session deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Serve Frontend (Admin Console) ────────────────────────────────────────────

FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")

if os.path.exists(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    @app.get("/admin")
    @app.get("/admin/{path:path}")
    async def serve_admin():
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))
