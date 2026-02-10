# Technical Architecture Document (TAD) - Collig

## 1. System Architecture
The system consists of a Frontend (UI), a Backend (AI Core & API), and a Database (Marketplace Data).

### 1.1. High-Level Diagram
```mermaid
graph TD
    User[User] -->|Interacts| Frontend[Frontend (Vue + Vite)]
    Frontend -->|API Calls| Backend[Backend (Python + FastAPI)]
    Backend -->|OS Commands| OS[Operating System]
    Backend -->|DB Queries| DB[(Database)]
    Backend -->|AI Inference| LLM[LLM Service]
```

## 2. Technology Stack

### 2.1. Frontend
- **Framework**: Vue 3
- **Build Tool**: Vite
- **State Management**: Pinia
- **Routing**: Vue Router
- **Styling**: Tailwind CSS (recommended) or scoped CSS

### 2.2. Backend
- **Language**: Python 3.10+
- **Framework**: FastAPI
- **AI/LLM Integration**: LangChain or direct API calls (OpenAI/Anthropic)
- **OS Interaction**: `subprocess`, `os`, `pyautogui` (for UI automation)
- **Skill Loading**: Dynamic module loading

### 2.3. Database & Storage
- **Database**: SQLite (local dev), PostgreSQL (production marketplace)
- **Key-Value Store**: Redis (optional, for caching/queues)

## 3. Module Design

### 3.1. Core Agent
- **Orchestrator**: Parses user input and delegates to skills.
- **Context Manager**: Maintains conversation history and OS context.

### 3.2. Skill Manager
- **Loader**: Scans and loads skill plugins.
- **Executor**: Runs skill functions safely.
- **Registry**: Metadata about available skills.

### 3.3. Marketplace API
- **Endpoints**: `/skills`, `/users`, `/transactions`
- **Auth**: JWT-based authentication.

## 4. Development Workflow
- **Frontend**: `npm run dev`
- **Backend**: `uvicorn main:app --reload`
- **Config**: `.env` file for API keys and secrets.
