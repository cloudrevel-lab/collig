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
| `make terminal-image` | Build the Docker image used by the browser terminal (one-time) |
| `make terminal-app` | Build + run the full terminal-first console on :5006 (Terminal landing + sidebar) |
| `make terminal-app-stop` / `terminal-app-status` | Stop / inspect the terminal-first console |
| `make push-personas personality=<path>` | Validate a persona and open a PR against cloudrevel-lab/collig-personas |
| `make test` | Run the harness/router/config and provider round-trip tests |
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
│   ├── cli.py             # Interactive Rich CLI (entrypoint for 'make pa'); commands, completer, !shell
│   ├── agent.py           # Legacy LangChain/LangGraph agent (kept for compatibility)
│   ├── main.py            # FastAPI app (REST API + serves the built frontend)
│   ├── runner.py          # ADK AgentService: the execution engine for CLI and web
│   ├── harness.py         # Intent router, direct /<tool> calls, !shell runner
│   ├── thinking.py        # Structured thinking/planning timeline for the CLI
│   ├── config_ui.py       # Provider-scoped /config screen stack
│   ├── runtime.py         # config.json helpers, provider/model resolution, DEFAULT_MODELS
│   ├── paths.py           # Canonical paths (~/.collig for config/data/sessions) - 'paths' singleton
│   ├── session.py         # SessionManager (chat history persistence)
│   ├── list_sessions.py   # 'make list-sessions' implementation
│   ├── menu.py, news_cache.py  # CLI helpers
│   ├── user_memory.py     # persistent user profile (facts/routines/usage) + extraction
│   ├── personality.py     # /distill dossiers + /chatto activation
│   ├── persona_market.py  # /load-personas client: catalogue, checksums, safe install
│   ├── commands.py        # shared /distill, /chatto, /personality, /memory, /load-personas handlers
│   ├── llm.py             # provider-agnostic background completion (litellm)
│   ├── terminal.py        # Browser terminal: auth, PTY, Docker sandbox, session lifecycle
│   ├── terminal_routes.py # Shared terminal HTTP/WebSocket router (console + standalone)
│   ├── terminal_app.py    # Standalone terminal-only FastAPI app (no chat/config/admin)
│   └── .env               # Local secrets (OPENAI_API_KEY, DASHSCOPE_API_KEY, ...) - gitignored
│
├── terminal/              # Web-terminal Docker image + per-session relay sidecar
│   ├── Dockerfile         # CLI + deps, no secrets, no host mounts
│   └── relay.py           # Forwards only /v1/{chat,embeddings,models} to the host proxy
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
│   │                      #        profile, git, diary, jira, web_search, flight, ...
│   └── imported/          # Drop-in external skills (each subdir has its own SKILL.md)
│
├── frontend/              # Vue 3 + Vite + Vuetify admin console
│   ├── src/               # App.vue, views/, components/, composables/, router.js
│   ├── terminal.html      # Terminal-only build entry
│   ├── vite.terminal.config.js  # Builds dist-terminal (TerminalView only)
│   └── dist-terminal/     # Served by core.terminal_app (gitignored build output)
│
├── assets/                # Banner and static assets
└── docs/                  # PRD.md, Technical_Architecture.md
```

---

## One harness, two surfaces

`core/cli.py` (CLI) and `core/main.py` (FastAPI) both use
`core.runner.get_agent()`, i.e. the ADK harness in `agents/collig/`:

1. **Google ADK harness** — `agents/collig/` + `core/runner.py`. One long-lived
   `App`/`Runner`; `SkillToolset` narrows the tools per turn; `TracePlugin`
   records the trace; sub-agents own Jira/email/survey.
2. **Legacy LangChain/LangGraph** — `core/agent.py`. Kept for compatibility and
   migration; it is no longer on the `make pa` path. Do not add new features
   there; port them to the ADK harness instead.

Provider/model logic lives in `core/runtime.py` (resolution and storage) and
`agents/collig/providers.py` (LiteLLM construction). Both surfaces read the
same config, so update `core.runtime.set_llm_field` rather than writing
`LLM_PROVIDER`/`LLM_MODEL` by hand.

**Per-turn tool selection is keyword-based.** `SkillToolset` offers only the
skills that match the current message, so a reply like `ok` or `the rest of the
week` matches nothing on its own. `core.harness.route_with_context` keeps the
previous turn's skills for reply-shaped messages (see `is_followup_message`),
and `SkillToolset` reads the earlier user messages from the ADK session to do
it. Keep that behaviour when changing the router: without it the model sees the
conversation but has no tool to act on it.

Parameter answers count as follow-ups too. After the assistant asks "tell me
your city", `the location is Oatlands NSW 2117` / `in Oatlands` / a bare
`Oatlands NSW 2117` must keep `get_weather` offered. If the tool is removed,
the model still remembers it from the previous turn and calls it. The
place/postcode and `the <field> is ...` patterns in `is_followup_message` are
what keep that working. `UnroutedToolPlugin` (`agents/collig/plugins.py`) is
the last line of defence: a call to a tool the turn did not offer is answered
with a normal function response instead of failing the invocation, and run only
when the tool belongs to a skill this agent owns and does not write, send or
delete. Watch the log for `Routing gap:` lines — each one is a missing keyword.

**The keyword lists are multilingual on purpose.** `SKILL_KEYWORDS` in
`core/harness.py` carries Chinese terms for every user-facing skill, and
`_keyword_score` matches CJK by substring because `\b` never matches between
two ideographs (`re.search(r"\b新闻\b", "最近澳洲有哪些新闻")` finds nothing).
An English-only list silently gates a whole language out of the tool catalogue:
`最近澳洲有哪些新闻，给我讲一下` routed to no skill, the model was offered only
`transfer_to_agent`, called `search_news` anyway, and ADK failed the turn with
`Tool 'search_news' not found`. When adding a skill or a trigger, add its
Chinese wording at the same time.

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
- `config` — provider-scoped configuration UI. `Model Provider` opens one
  provider's own page; `Esc` goes back one level, `q` quits.
- `config set <KEY> <VALUE>` — set a single config value
- `!<command>` — run a shell command (`!pwd`, `!git status`)
- `/<tool> [args]` — call one tool directly with no model round-trip
- `/distill <person> [--for <reason>]` — collect resources into
  `~/.collig/personalities/<slug>/`; `--for` records why you want the persona
  (the reason is otherwise inferred)
- `/chatto <person>` / `/chatto off` — activate/deactivate a distilled persona
- `/personality` — show or switch the active persona
- `/load-personas [list|<number|name>|--all|--force <name>|search <text>|refresh]`
  — browse and install personas from cloudrevel-lab/collig-personas; installs
  are checksum-verified and never execute market content
- `/memory [list|search|forget|note|clear|on|off|proactive|extract|path]` — view
  and control the persistent user profile
- Argument completion — `/chatto`, `/personality`, `/distill show|rm` and
  `/memory forget` list available names/keys after the trailing space; ↑/↓
  picks, Tab/Space accepts. `_argument_position` in `core/cli.py` decides where
  Space is a selection vs a literal separator, so `/jira ` keeps its old
  behaviour.
- `/news last` / `/news load <n>` / `/news save` / `/news cached` — reopen
  a cached news list; every search is cached automatically. After a news
  answer the CLI only prints a one-line hint (`news_browse_hint`); it must not
  auto-open the browser, because that is a modal prompt_toolkit application
  that hides the `You:` prompt until Esc and reads as "the chat input is gone".
- `status` / `doctor` — check the LLM connection and system health
- `stats` — token usage statistics

Tests: `make test` runs `tests/test_harness.py` (router, lazy skills, config
scoping, shell/direct tools), `tests/test_flight_skill.py` (airport resolution,
dates, rendering, routing -- offline), `tests/test_llm_config_menu.py`,
`tests/test_cli_completion.py`, the news tests, `tests/test_user_memory.py`
(extraction, dedupe/confidence, routines, prompt block) and
`tests/test_personality.py` (distill/activate/commands, all offline via fakes) and
`tests/test_web_terminal.py` (token/ticket/Origin checks, per-session config,
Docker command hardening, relay allow-list, PTY smoke test -- offline),
`tests/test_terminal_app.py` (standalone app serves only /health, terminal routes
and the terminal SPA; chat/config/admin routes are absent) and
`tests/test_persona_market.py` (checksum/size/slug/secret checks, cache fallback,
command dispatch; offline via an injected fetcher).

Example for a custom endpoint:

```
config set CUSTOM_BASE_URL https://my-host/v1
config set CUSTOM_API_KEY sk-...
provider custom my-model-name
```

---

## Persona market

Collig is the authoring tool; the separate cloudrevel-lab/collig-personas repo is
the distribution channel. Keep that split:

- /distill and hand edits create personas under ~/.collig/personalities;
- /load-personas in core/persona_market.py + core/commands.py installs market
  copies with checksum, size, slug and secret checks; make push-personas uses
  scripts/push_persona.py to validate a local persona, run the market's tests,
  regenerate index.json and open a PR;
- the market is data-only. Never make Collig download or execute scripts from a
  persona. A dossier is still untrusted prompt content, so reviewers must check
  for prompt-injection text as well as voice/factual quality;
- index.json is generated by the market's scripts/build_index.py and contains
  SHA-256 checksums for every file. The client refuses mismatches, unknown files,
  traversal slugs, oversize files and obvious credentials;
- market CI (.github/workflows/validate.yml) runs the same validator and tests.
  A stale index or duplicate slug fails; duplicate canonical names warn so
  disambiguated people remain possible;
- use COLLIG_PERSONAS_REPO/COLLIG_PERSONAS_REF for forks and mirrors. The cache
  lives at ~/.collig/personas-market/index.json and is used if GitHub is offline;
- publishing needs gh auth login; a missing login must fail clearly rather than
  silently committing. The PR body is generated by the publisher.

When changing the persona data contract, update all of: the market validator,
the market tests, core/persona_market.py validation, tests/test_persona_market.py
and the README/CONTRIBUTING docs.

---

## Browser terminal (web)

The **Terminal** page (/terminal in the SPA) is a real xterm.js PTY, not a chat
facade. core/terminal.py owns access control, session lifecycle and the sandbox;
core/terminal_routes.py exposes the shared HTTP/WebSocket routes and the
host-side LLM proxy; terminal/relay.py is the only process the sandbox can
reach. core/main.py includes that router for the full console.

Port 5005 and port 5006 both run core.main. The server injects
COLLIG_LANDING_VIEW into index.html; 5005 defaults to Chat, while
make terminal-app sets terminal so the same SPA lands on /terminal with the
normal sidebar. core/terminal_app.py remains an optional terminal-only app
(no /api/chat or admin routes); core/main.py is the terminal-first console.

Build the normal SPA with "cd frontend && npm run build". The optional
terminal-only bundle is "npm run build:terminal" (terminal.html +
src/main-terminal.js). The terminal-only app assumes a root base path.

Resuming a web session: SessionsView pushes /terminal?session=<id>;
TerminalView reads the hash query and sends session_id when creating the
terminal session. TerminalManager copies only that host session JSON into the
sandbox, builds the CLI with --session, and syncs just that session back on
cleanup. Tests cover seeding, --session, invalid ids and sync-back.

The terminal has its own Vuetify theme names (colligTerminalDark/Light) supplied
through v-theme-provider around the card. Default is dark and the choice is
stored under collig-terminal-color, independent of the console-wide theme. When
toggling, update both the provider and term.options.theme.

- **Never run the CLI directly in the server process for this feature.**
  !<command> is a shell. Command deny-lists are bypassable; only the container
  boundary is meaningful. Each session gets a fresh HOME/workspace, a read-only
  root, no capabilities, resource limits and an --internal network.
- **The sandbox must never contain provider credentials or a bearer proxy
  token.** The generated ~/.collig/config.json contains only the relay URL
  (http://relay:8080/v1) and the literal placeholder key relay-managed. The
  relay sidecar holds the per-session token; the host proxy injects the real
  provider key and forces the configured model. Do not put the token back in
  the sandbox config: the user can read it with !cat or /config list.
- **The relay is an allow-list, not a general proxy.** It accepts only
  /v1/chat/completions, /v1/completions, /v1/embeddings and /v1/models and maps
  them to the fixed session prefix. Do not make its upstream caller-controlled.
- **Auth is opt-in friction for localhost, mandatory for remote.** A loopback
  peer with no forwarding headers gets the generated token from
  /api/terminal/bootstrap; any X-Forwarded-For / Forwarded / CF-Connecting-IP
  disables that, because a reverse proxy makes every peer look local. Shared
  deployments must set COLLIG_TERMINAL_TOKEN. WebSocket connections also require
  a same-origin Origin header and a one-shot ticket.
- **The rest of the console still has no accounts.** The terminal hardens its own
  surface; do not expose /api/config, /api/chat or skill endpoints publicly
  without an authenticating reverse proxy. Say this in docs when changing auth.
- Default network mode is internal: the model proxy works, but weather/news/
  flight skills cannot reach the Internet. COLLIG_TERMINAL_NETWORK=bridge is a
  trusted-local escape hatch and gives the sandbox a route to the host/LAN.
- Tests must not require Docker: mock TerminalManager._docker and inspect the
  command builders, as tests/test_web_terminal.py does. Clean up sessions with
  the manager so temp dirs do not leak.

---

## Config, data & secrets

- Runtime state lives under **`~/.collig/`**: `config.json`, `sessions/`,
  `data/` (per-skill vector stores), `configs/`, `storage/`, `memory/`,
  `personalities/`. See `core/paths.py`.
- **User memory** (`core/user_memory.py`) is stored as
  `~/.collig/memory/profile.json` (facts, interests, habits, tool usage) plus
  the generated `USER.md` and an append-only `events.jsonl`. It is injected
  into the system instruction on every turn by `agents/collig/agent.py`.
  `core/runner._run_turn` captures each finished turn; `SkillToolset` offers a
  routine's skill on a greeting when one is due. Config switches:
  `USER_MEMORY_ENABLED`, `USER_MEMORY_LLM_EXTRACT`, `USER_MEMORY_PROACTIVE`,
  `USER_MEMORY_MAX_FACTS`, `USER_MEMORY_PROMPT_CHARS`.
- **Personalities** (`core/personality.py`) live in
  `~/.collig/personalities/<slug>/` (`PERSONALITY.md`, `meta.json`,
  `sources.md`); `active.json` tracks the current one. Distillation is
  **essence-first**: a separate `_build_brief` call returns structured JSON
  (`essence`, `emotional_register`, `voice_mode`, `why_users_distill`,
  `use_modes`, `quote_habit`, `own_words`, `sample_exchanges`) before the
  dossier call runs. `own_words` must be verbatim and confidence-scored; low
  confidence lines are kept as `（待核对）` in the file but are filtered out of
  the prompt. The model's prose is wrapped by deterministically rendered
  sections (`## Essence`, `## Their own words`, `## How to quote and compose`,
  `## Voice samples`), so the exact lines and worked examples never depend on
  the prose call following formatting instructions. If the brief call fails,
  `brief_from_markdown` derives a degraded core and the dossier still works.
- The full dossier is appended after the memory block, but a compact **style
  card** (essence, why the user distilled them, verbatim lines, quote/compose
  rules, first operating rules, one worked example) is placed at the top of
  the instruction. For `voice_mode: poet` the contract requires at least one
  line of verse in most replies -- quoted from `own_words` or newly composed
  in the same form, and a new piece must be labelled as new (`我新填一阕…`),
  never attributed to an extant work. A switch adds a one-turn
  `PERSONA SWITCH` note telling the model not to imitate earlier assistant
  turns. This is deliberate: a dossier only at the end lost to the most recent
  assistant messages, so switching from Albanese to Trump kept "mate" in the
  reply. `PERSONALITY_PROMPT_CHARS` bounds the injected dossier.
- `/distill <name> --for <reason>` records the user's own purpose in the brief
  and `meta["user_intent"]`; when omitted the brief pass infers it. The
  rendered Essence section carries both "Your stated reason" and "Why you
  would talk to them", which is how a request for 李煜 becomes "quote his own
  词, then compose a new one in his 词牌" rather than a biography.
- **Same-name disambiguation** is part of `/distill`: `identify_candidates`
  runs a candidate pass (with a deliberate namesake check and a second pass
  when the model finds only one person), and `distill` returns
  `needs_choice` until the user picks. Pending candidates live in
  `~/.collig/personalities/.pending.json`; `/distill 宋佳 2`, `--pick 2`, and
  the CLI arrow-key chooser all consume them. `meta["name"]` is the
  distinguishable display name (小宋佳), `meta["canonical_name"]` is the
  shared name (宋佳), and `aliases` carries both. `find_all` is the
  ambiguity-aware lookup used by `/chatto`, `/distill show|rm`; `resolve`
  only returns when the answer is unambiguous. Folder names use
  `folder_slug`, which keeps CJK characters (unlike the ASCII `slugify`).
  Synthesis only receives the selected candidate's context and sources.
- Secrets: `OPENAI_API_KEY`, `DASHSCOPE_API_KEY`, `DEEPSEEK_API_KEY`,
  `CUSTOM_API_KEY`, `JIRA_*`, etc. — read from env first, then `config.json`
  (see `get_api_key`). Store locally in `core/.env` or via `config set`; never
  commit them.

---

## User memory & personalities

Two features share one principle: **plain files over an opaque store**.

- `core/user_memory.py` is the source of truth for what Collig knows about the
  user. A JSON file plus a generated Markdown view is enough for a personal
  profile; it needs no embedding key, is easy to inspect and back up, and can
  be injected into the prompt reliably. The store dedupes by key, records
  source/confidence/timestamps, merges family/project details, protects
  explicit facts from inferred overwrites, and rejects secret-shaped values.
  Capture is synchronous for rules and location counting, then an optional
  daemon-thread LLM pass enriches it (`core/llm.complete`). Never make the user
  wait for memory.
- Routine tracking is what turns memory into proactivity. `record_skill_usage`
  counts tools that actually ran, per time-of-day bucket. On a greeting,
  `SkillToolset._routine_skills` offers the due routine's skill and
  `TrivialQueryPlugin` keeps the tool declarations, so the model can act on
  "they check the news every morning" instead of stripping all tools for
  "hello". `mark_proactive` limits it to once per bucket per day.
- `core/personality.py` writes `PERSONALITY.md` per persona and injects it
  last in the instruction (voice wins over generic tone, safety text wins over
  both), with the essence-first style card at the top. `/distill` and
  `/chatto` are implemented in `core/commands.py` and handled both by the CLI
  and by `AgentService._dispatch`, so the web chat accepts the same slash
  commands. Distillation (identity, character core, dossier) and memory
  extraction are the only features that call `core.llm` directly; the
  conversation itself still goes through ADK/LiteLLM.
- Tests must not touch the real `~/.collig`: `UserMemoryStore` and
  `PersonalityManager` accept an explicit root (and injectable
  `config_loader`/`complete`/`search`), which is how the offline tests work.

---

## Skills

- A skill is a directory with an `__init__.py` (subclass of `skills.base.Skill`)
  and a `SKILL.md` (YAML frontmatter + instructions).
- **Registration is lazy.** `core.runtime._build_skill_manager()` eagerly
  imports only the tiny builtins (Time/Browser/Thinking Toggle). Every other
  skill becomes a `skills.base.LazySkill`, which reads only SKILL.md until the
  router first selects it.
- `SKILL.md` frontmatter is the source of truth for routing and the Skills
  page: put `name`, `description`, `triggers`, `tools` and
  `config.required` there. The router also falls back to each skill's
  `triggers` property.
- **External/imported** skills are auto-discovered from `skills/imported/`.
  Drop a new skill dir there and restart.
- `SkillManager.register_skill` dedupes by skill name, so a skill is never
  registered (or its tools exposed) twice.

### Startup performance notes

- Never import a skill module or make a network call from `Skill.__init__` /
  `configure()` unless it is genuinely cheap. `LazySkill` defers both until
  the skill is selected. The Bookmarks skill used to call the embeddings API
  during `configure()`; that is exactly the pattern to avoid.
- `AgentService.tools` returns `ToolStub` objects (name/description only) so
  the CLI completer and `/api/skills` never force the registry open.
- ADK's `FunctionTool` needs a plain function. Wrap LangChain tools with
  `skills.tooling.as_adk_function()` before passing them to ADK.

---

## Public APIs for new skills

Most new capabilities are one HTTP call away, and starting from an API is almost
always cheaper than scraping or hand-rolling a client. The catalogue to check
first is **[public-apis/public-apis](https://github.com/public-apis/public-apis)**:
roughly 1,400 free APIs grouped by category, each tagged with auth, HTTPS and
CORS support. It answers the two questions that decide a skill's shape — does an
API already exist, and does it need a key?

### Choosing an API

1. **No key first.** A key-less API makes a skill work on a fresh install, in
   tests and in the web surface with no setup. Prefer it even if a keyed one is
   marginally better; add the key only when the free tier is genuinely required.
2. **Read the terms, not just the badge.** "Free" often means a quota, an
   attribution requirement or "no commercial use". Scraping a site that has no
   API is a different decision from calling a licensed feed — say which one the
   skill does, in SKILL.md.
3. **HTTPS + JSON, with a timeout.** The skill runs inside a turn; a hung socket
   is a hung conversation. Cap the timeout and keep the payload small.
4. **Keep the network call inside the tool.** Never in `__init__`/`configure()`
   — see the startup-performance note above. `LazySkill` cannot save a skill
   that phones home while being registered.
5. **Fail with a sentence.** A raised exception aborts the whole ADK invocation,
   so tools catch and return an explanation, as `skills/flight` and
   `skills/weather` do.
6. **Declare the key, don't hard-code it.** Put it in `config.required` in
   SKILL.md, read it through `core.runtime.get_api_key` (env first, then
   `config.json`), and never commit it.

### Categories that map onto Collig skills

| Need | Good starting points | Key? |
| --- | --- | --- |
| Flights / travel | Amadeus Self-Service, Duffel, Kiwi Tequila, AeroDataBox | yes |
| Weather | Open-Meteo (used by Weather Reporter), OpenWeatherMap | no / yes |
| News | NewsAPI, GNews, The Guardian, Hacker News | some |
| Maps / geocoding | OSM Nominatim, Open-Meteo geocoding (used by Weather), OSRM | no |
| Finance / FX | Frankfurter, Alpha Vantage, CoinGecko | no / yes |
| Developer | GitHub REST, Hacker News (Firebase), Stack Exchange | mostly no |
| Reference | Open Library, Crossref, arXiv, Wikipedia / Wikidata | no |
| Transport | Transport for NSW Open Data, GTFS feeds, Translink | some |
| Food / health | Open Food Facts, TheMealDB | no |
| Space / science | NASA Open APIs, USGS | no |

### Worked example: `skills/flight/`

The Flight Search skill is the template for "add an API-backed tool":

- `airports.py` resolves city names to IATA codes **offline** (`airportsdata`),
  so the deterministic part is testable without network.
- `__init__.py` builds the Google Flights query, fetches it, tolerantly parses
  the result payload and renders a ranked list plus booking links. No API key,
  so it works out of the box; every failure path returns a sentence.
- `SKILL.md` carries the triggers, so the router finds the skill with no edit to
  `core/harness.py` (the curated `SKILL_KEYWORDS` entry is a boost, not a
  requirement).
- `tests/test_flight_skill.py` covers resolution, dates, rendering and routing
  offline; only the live search needs the network.

If a licensed feed is ever required, put it behind the same `search_flights`
signature: Amadeus (free test tier), Duffel (test mode) and Kiwi/Tequila all
return itineraries that map onto the existing renderer, and their keys belong in
`config.json` via `config set`.

---

## Conventions

- Python: format with **black** and **isort**, lint with **flake8**, all at
  **max line length 120** (see `make lint`).
- Use `uv` for Python execution/deps (do not call `pip` directly).
- Frontend: Vue 3 SFCs under `frontend/src`, built with Vite; `make console-build`
  produces `frontend/dist` which the FastAPI app serves.
