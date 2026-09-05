# AGENT.md

Guidance for AI coding agents (and humans) working in the **Collig** repository.

Collig is a locally-running AI co-worker: a Python backend with a modular skill
system, a Rich terminal CLI, and a Vue 3 web admin console.

---

## Quick start

All common tasks are driven through the **Makefile** (run `make help` to list them).

| Command | What it does |
| --- | --- |
| `make install` | Install core deps (via `uv`) and frontend deps (via `npm`) |
| `make pa` | **Start the interactive CLI co-worker** (the primary dev/run entrypoint) |
| `make pa session=<ID>` | Resume a saved chat session |
| `make pa prompt="..."` | Run a single prompt non-interactively |
| `make list-sessions` | List saved chat sessions |
| `make core` | Start only the FastAPI backend (uvicorn, auto-reload) |
| `make frontend` | Start only the Vite frontend dev server |
| `make up` / `make dev` | Start core + frontend together |
| `make console-start` | Build frontend and start the admin console on :5005 |
| `make console-stop` | Stop the admin console |
| `make console-status` | Check whether the admin console is running |
| `make lint` | Run isort + black + flake8 (max line length 120) |

> The Makefile runs Python commands through **`uv`** (e.g. `cd core && uv run python cli.py`).
> Prefer `make` targets over calling scripts directly so paths and the venv are set up correctly.

---

## Project layout

```
collig/
├── Makefile               # Command hub - see table above
├── pyproject.toml         # Python project + dependencies (managed by uv; uv.lock is the lockfile)
├── README.md              # User-facing docs
├── AGENT.md               # This file
│
├── core/                  # Python backend
│   ├── cli.py             # Interactive Rich CLI (entrypoint for 'make pa'); commands, config UI, completer
│   ├── agent.py           # Legacy LangChain/LangGraph agent (class Agent + module-level singleton 'agent')
│   ├── main.py            # FastAPI app (REST API + serves the built frontend at /admin)
│   ├── runner.py          # ADK-based runner used by the newer agent stack
│   ├── runtime.py         # config.json helpers, provider/model resolution, DEFAULT_MODELS
│   ├── paths.py           # Canonical paths (~/.collig for config/data/sessions) - 'paths' singleton
│   ├── session.py         # SessionManager (chat history persistence)
│   ├── list_sessions.py   # 'make list-sessions' implementation
│   ├── menu.py, news_cache.py  # CLI helpers
│   └── .env               # Local secrets (OPENAI_API_KEY, DASHSCOPE_API_KEY, ...) - gitignored
│
├── agents/collig/         # Newer Google ADK agent stack (parallel to core/agent.py)
│   ├── agent.py           # Root LlmAgent + ADK App
│   ├── providers.py       # config.json -> LiteLlm provider/model resolution; list_available_models()
│   ├── toolsets.py        # Exposes skills as ADK tools
│   ├── subagents.py       # Sub-agent construction
│   └── plugins.py         # TokenStats + TrivialQuery plugins
│
├── skills/                # Modular skill system (agentskills.io / SKILL.md compatible)
│   ├── base.py            # Skill ABC + load_skill_from_path / discover_skills
│   ├── manager.py         # SkillManager: registration (dedup by name), tool collection, intent matching
│   ├── loader.py          # SkillLoader: load skills from a directory
│   ├── builtins/          # Time, Browser, ThinkingToggle skills
│   ├── <skill>/           # One dir per built-in skill (each has __init__.py + SKILL.md)
│   │                      #   e.g. filesystem, email, weather, memory, bookmark, news,
│   │                      #        profile, git, diary, jira, web_search, ...
│   └── imported/          # Drop-in external skills (each subdir has its own SKILL.md)
│
├── frontend/              # Vue 3 + Vite + Vuetify admin console
│   └── src/               # App.vue, views/, components/, composables/, router.js
│
├── assets/                # Banner and static assets
└── docs/                  # PRD.md, Technical_Architecture.md
```

---

## Two agent stacks (important)

There are **two** agent implementations sharing the same skills and sessions:

1. **Legacy LangChain/LangGraph** — `core/agent.py`. This is what `make pa`
   (`core/cli.py`) uses via `from agent import agent`. `agent = Agent()` is a
   module-level singleton created at import time.
2. **Google ADK** — `agents/collig/` + `core/runner.py`. The newer stack used
   by `adk web` / the FastAPI server.

Provider/model logic is duplicated across both (`core/agent.py` and
`agents/collig/providers.py`). **When changing provider behaviour, update both.**

---

## LLM providers & models

Configured via `~/.collig/config.json` (`LLM_PROVIDER`, `LLM_MODEL`) and/or
environment variables / `core/.env`. Supported providers:

- `openai` (needs `OPENAI_API_KEY`)
- `deepseek` (needs `DEEPSEEK_API_KEY`; OpenAI-compatible)
- `dashscope` (阿里云; needs `DASHSCOPE_API_KEY`, endpoint via `DASHSCOPE_ENDPOINT`)
- `ollama` / `llama` (local; no key)
- `custom` — **any OpenAI-compatible endpoint**. Set `CUSTOM_BASE_URL`
  (required, e.g. `https://my-host/v1`) and `CUSTOM_API_KEY` (optional for local
  servers). The model comes from `LLM_MODEL`.

### Useful CLI commands (inside `make pa`)

- `provider` — show the current provider and model
- `provider list` — **list all providers and their available models**
  (also queries `ollama list` for locally installed models)
- `provider <name> [model]` — switch provider (persists to config.json)
- `config` — interactive configuration manager (set API keys, base URLs, etc.)
- `config set <KEY> <VALUE>` — set a single config value
- `status` / `doctor` — check the LLM connection and system health
- `stats` — token usage statistics

Example for a custom endpoint:

```
config set CUSTOM_BASE_URL https://my-host/v1
config set CUSTOM_API_KEY sk-...
provider custom my-model-name
```

---

## Config, data & secrets

- Runtime state lives under **`~/.collig/`**: `config.json`, `sessions/`,
  `data/` (per-skill vector stores), `configs/`. See `core/paths.py`.
- Secrets: `OPENAI_API_KEY`, `DASHSCOPE_API_KEY`, `DEEPSEEK_API_KEY`,
  `CUSTOM_API_KEY`, `JIRA_*`, etc. — read from env first, then `config.json`
  (see `get_api_key`). Store locally in `core/.env` or via `config set`; never
  commit them.

---

## Skills

- A skill is a directory with an `__init__.py` (subclass of `skills.base.Skill`)
  and a `SKILL.md` (YAML frontmatter + instructions).
- **Built-in** skills are registered explicitly in
  `Agent._register_initial_skills` (`core/agent.py`) as imported classes.
- **External/imported** skills are auto-discovered from `skills/imported/`
  by `Agent._load_external_skills`. Drop a new skill dir there and restart.
- `SkillManager.register_skill` dedupes by skill name, so a skill is never
  registered (or its tools exposed) twice.

### Startup performance notes

- Heavy vector-store deps (`langchain_chroma` → `chromadb`, ~0.6s) are imported
  **lazily** in the memory/bookmark/profile/email/diary skills via a local
  `_load_vectorstore_deps()` helper — only when those features are actually used.
  Keep new skills lazy about heavy imports too.
- `langchain_openai` (~2s) is imported eagerly by `core/agent.py` and is the
  dominant, largely irreducible cost of the legacy stack's startup.

---

## Conventions

- Python: format with **black** and **isort**, lint with **flake8**, all at
  **max line length 120** (see `make lint`).
- Use `uv` for Python execution/deps (do not call `pip` directly).
- Frontend: Vue 3 SFCs under `frontend/src`, built with Vite; `make console-build`
  produces `frontend/dist` which the FastAPI app serves.
