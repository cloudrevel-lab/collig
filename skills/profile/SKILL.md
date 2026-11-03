---
name: Personal Profile
description: Remembers durable facts and preferences about the user across sessions
version: 2.0.0
author: Collig Team
license: MIT

tools:
  - name: set_personal_info
    description: Explicitly remember a durable fact about the user
  - name: get_personal_info
    description: Look up remembered information about the user
  - name: list_personal_info
    description: List everything currently remembered about the user
  - name: forget_personal_info
    description: Forget one remembered fact
  - name: record_user_habit
    description: Record a recurring routine Collig should act on

config:
  required: []
  optional:
    - USER_MEMORY_ENABLED: Turn automatic user memory on or off (default on)

triggers:
  - remember this
  - remember that
  - save this about me
  - my preference
  - personal info
  - about me
  - my location
  - my name
  - what do you know about me
---

# Personal Profile Skill

Collig keeps a persistent, inspectable profile of the user so it can behave
like a colleague who already knows them: home city, family details, projects,
preferences and recurring routines.

## Storage

- `~/.collig/memory/profile.json` — source of truth (facts, interests, habits,
  skill usage)
- `~/.collig/memory/USER.md` — generated, human-readable view
- `~/.collig/memory/events.jsonl` — append-only audit log

Facts are injected into the system prompt on every turn. Automatic capture is
model-free first (rules for "I live in...", "my daughter...", repeated weather
locations, repeated tool use) and optionally enriched by a background LLM call.

## Usage

The user normally does not need to call this skill: durable facts are captured
automatically. Use the tools when the user explicitly says "remember this",
corrects a remembered fact, or asks what Collig knows about them.

## Tools

### set_personal_info(key, value, category="other") -> str

Explicitly store a fact. Categories: identity, location, family, work,
preference, routine, project, event, other. Rejects secrets.

### get_personal_info(query) -> str

Lexical lookup over remembered facts.

### list_personal_info() -> str

Everything remembered, with keys for `/memory forget`.

### forget_personal_info(key) -> str

Remove one fact.

### record_user_habit(intent, description, time_of_day="any") -> str

Record a routine such as "checks AI news in the morning". A due routine makes
Collig act proactively on a greeting and offers the matching skill.

## Commands

- `/memory` — show the profile
- `/memory forget <key>` / `/memory clear`
- `/memory on|off`, `/memory proactive on|off`, `/memory extract on|off`

## Notes

- No vector database and no embedding key are required.
- Explicit facts outrank inferred ones; a user correction outranks both.
- Memory can be disabled entirely with `/memory off` or
  `config set USER_MEMORY_ENABLED false`.
