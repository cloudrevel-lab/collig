"""
Shared handlers for Collig's "about me" slash commands.

``/distill``, ``/chatto``, ``/personality`` and ``/memory`` must behave the
same in the terminal and in the web chat, so the parsing/output lives here and
both surfaces call :func:`handle_slash_command`.

The handler returns ``None`` when the text is not one of these commands, so
callers can fall through to normal tool/model handling.
"""

from __future__ import annotations

import os
import re
from typing import Any, Callable, Optional

META_COMMANDS = {"distill", "chatto", "personality", "memory", "load-personas", "personas"}

DISTILL_HELP = """Usage:
  /distill <name>           Collect resources and build a personality folder
  /distill <name> --force   Rebuild an existing personality
  /distill <name> --for <reason>
                            Say why you want this person (otherwise inferred)
  /distill list             List distilled personalities
  /distill show <name>      Print a dossier
  /distill rm <name>        Delete a personality

Examples:
  /distill Spider-Man
  /distill 李煜 --for 想听他用自己的词回应，也想让他新填一阕
  /distill Ada Lovelace
  /chatto Spider-Man
"""

CHATTO_HELP = """Usage:
  /chatto <name>     Speak and think as a distilled personality
  /chatto off        Return to plain Collig
  /chatto list       List personalities
  /chatto            Show the active personality

Create one first with /distill <name>.
"""

PERSONAS_HELP = """Usage:
  /load-personas                 List the shared persona market
  /load-personas <number|name>   Install one persona
  /load-personas --force <name>  Replace an installed persona
  /load-personas --all           Install everything not already present
  /load-personas search <text>   Search names, aliases and descriptions
  /load-personas refresh         Refresh the cached market catalogue

The market is cloudrevel-lab/collig-personas.  Create and edit personalities
locally with /distill; publish them with:
  make push-personas personality=~/.collig/personalities/<name>
"""

MEMORY_HELP = """Usage:
  /memory                     Show what Collig remembers about you
  /memory list                Same, as a list of facts
  /memory search <query>      Look up remembered facts
  /memory forget <key>        Remove one fact
  /memory note <text>         Explicitly remember a note
  /memory clear               Remove everything
  /memory on | off            Turn automatic memory on or off
  /memory proactive on | off  Allow routine-based proactive actions
  /memory extract on | off    Allow the background LLM to enrich memory
  /memory path                Show where memory is stored

Memory is stored as readable JSON + Markdown under ~/.collig/memory.
Notes are stored as plain text exactly as typed, including passwords/tokens
(Collig warns but does not refuse them).
"""


def _split_command(text: str) -> Optional[tuple[str, str]]:
    body = (text or "").strip()
    if body.startswith("/"):
        body = body[1:].strip()
    if not body:
        return None
    parts = body.split(None, 1)
    command = parts[0].lower()
    if command not in META_COMMANDS:
        return None
    return command, parts[1].strip() if len(parts) > 1 else ""


def _parse_distill_args(rest: str) -> tuple[str, bool, Optional[str], Optional[str]]:
    force = False
    pick: Optional[str] = None
    intent: Optional[str] = None
    # People copy the displayed name and append the flag without a space:
    # "/distill 李煜（南唐后主）--force".  Split a glued known flag off the name
    # before tokenising, otherwise "--force" becomes part of the person.  Only
    # the flags this command understands are split, so a reason that merely
    # contains "--" is left alone.
    rest = re.sub(r"(?<!\s)(--(?:force|pick|for|why)(?:=\S*)?)", r" \1", rest or "")
    tokens = []
    parts = rest.split()
    index = 0
    while index < len(parts):
        token = parts[index]
        if token in ("--force", "-f", "force"):
            force = True
        elif token in ("--pick", "-p"):
            if index + 1 < len(parts):
                pick = parts[index + 1]
                index += 1
        elif token.startswith("--pick="):
            pick = token.split("=", 1)[1]
        elif token.startswith("--for=") or token.startswith("--why="):
            intent = token.split("=", 1)[1].strip().strip("\"'") or None
        elif token in ("--for", "--why"):
            # Everything up to the next flag is free-form: the reason is a
            # sentence, not a single token.
            index += 1
            reason = []
            while index < len(parts) and not parts[index].startswith("--"):
                reason.append(parts[index])
                index += 1
            intent = " ".join(reason).strip().strip("\"'") or None
            continue
        else:
            tokens.append(token)
        index += 1
    return " ".join(tokens).strip(), force, pick, intent


def _choose_candidate(
    manager, title: str, candidates: list, choose: Optional[Callable[..., Optional[int]]]
) -> Optional[dict]:
    """Show a candidate picker when the surface supports one."""
    if choose is None or not candidates:
        return None
    from core.personality import format_candidate_line

    labels = [format_candidate_line(candidate) for candidate in candidates]
    try:
        index = choose(title, labels)
    except Exception:
        return None
    if index is None:
        return None
    try:
        index = int(index)
    except (TypeError, ValueError):
        return None
    if 0 <= index < len(candidates):
        return candidates[index]
    return None


def _memory_store():
    from core.user_memory import get_user_memory

    return get_user_memory()


def _personality_manager():
    from core.personality import get_personality_manager

    return get_personality_manager()


def _set_config(progress: Optional[Callable[[str], None]] = None, **values: Any) -> str:
    try:
        from core.runtime import update_config

        update_config(**values)
        return ""
    except Exception as exc:
        return f"Could not save the setting: {exc}"


def _handle_distill(
    rest: str,
    progress: Optional[Callable[[str], None]],
    choose: Optional[Callable[..., Optional[int]]] = None,
) -> str:
    manager = _personality_manager()
    lowered = rest.lower()
    if not rest or lowered in ("help", "-h", "--help"):
        return DISTILL_HELP + "\n" + manager.format_list()
    if lowered in ("list", "ls"):
        return manager.format_list()
    if lowered in ("show", "cat"):
        return "Usage: /distill show <name>  (use /distill list to see names)"
    if lowered in ("rm", "delete", "remove"):
        return "Usage: /distill rm <name>  (use /distill list to see names)"
    if lowered.startswith(("show ", "cat ")):
        name = rest.split(None, 1)[1].strip()
        matches = manager.find_all(name)
        if len(matches) > 1:
            selected = _choose_candidate(manager, f"Which {name}?", matches, choose)
            if selected is None:
                return manager.format_choice(name, matches, action="show")
            matches = [selected]
        if not matches:
            return f"No personality named '{name}'. Use `/distill list` to see what exists."
        meta = matches[0]
        path = manager.dossier_path(str(meta.get("slug")))
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return f"Could not read {path}: {exc}"
        return text[:20000]
    if lowered.startswith(("rm ", "delete ", "remove ")):
        name = rest.split(None, 1)[1].strip()
        result = manager.delete(name)
        if result.get("needs_choice"):
            selected = _choose_candidate(manager, f"Which {name}?", result.get("candidates") or [], choose)
            if selected is None:
                return str(result.get("message") or "")
            result = manager.delete(str(selected.get("slug") or selected.get("name")))
        return str(result.get("message") or "")

    name, force, pick, intent = _parse_distill_args(rest)
    if not name:
        return DISTILL_HELP
    # "/distill 宋佳 1" is accepted after the clarification (and on a later
    # retry, when the pending state has already been cleared).
    if pick is None:
        head, _, tail = name.rpartition(" ")
        if head and tail.isdigit():
            name, pick = head, tail
    result = manager.distill(name, force=force, pick=pick, progress=progress, intent=intent)
    if result.get("needs_choice"):
        candidates = result.get("candidates") or []
        selected = _choose_candidate(manager, f"Which {name}?", candidates, choose)
        if selected is None:
            return str(result.get("message") or "This name is ambiguous.")
        result = manager.distill(
            name,
            force=force,
            pick=candidates.index(selected) + 1,
            progress=progress,
            intent=intent,
        )
    if not result.get("ok"):
        return str(result.get("message") or "Distillation failed.")
    from core.personality import display_path

    lines = [str(result.get("message") or "")]
    summary = str(result.get("summary") or "").strip()
    if summary:
        lines.extend(["", "Summary: " + summary])
    display = str(result.get("name") or name)
    dossier = os.path.join(display_path(str(result.get("path") or "")), "PERSONALITY.md")
    lines.extend(
        [
            "",
            "Activate with `/chatto " + display + "`.",
            "Review or edit the dossier at " + dossier,
        ]
    )
    return "\n".join(lines)


def _handle_chatto(rest: str, choose: Optional[Callable[..., Optional[int]]] = None) -> str:
    manager = _personality_manager()
    lowered = rest.lower()
    if not rest:
        return manager.format_current()
    if lowered in ("help", "-h", "--help"):
        return CHATTO_HELP
    if lowered in ("list", "ls"):
        return manager.format_list()
    if lowered in ("off", "none", "stop", "reset", "default", "collig"):
        return str(manager.deactivate().get("message") or "")
    result = manager.activate(rest)
    if result.get("needs_choice"):
        selected = _choose_candidate(manager, f"Which {rest}?", result.get("candidates") or [], choose)
        if selected is None:
            return str(result.get("message") or "This name is ambiguous.")
        result = manager.activate(str(selected.get("slug") or selected.get("name")))
    return str(result.get("message") or "")


def _handle_personality(rest: str, choose: Optional[Callable[..., Optional[int]]] = None) -> str:
    manager = _personality_manager()
    lowered = rest.lower()
    if not rest:
        return manager.format_current()
    if lowered in ("list", "ls"):
        return manager.format_list()
    if lowered in ("off", "none", "stop", "reset", "default"):
        return str(manager.deactivate().get("message") or "")
    if lowered in ("help", "-h", "--help"):
        return CHATTO_HELP
    name = re.sub(r"^(?:use|on|activate)\s+", "", rest, flags=re.IGNORECASE).strip()
    result = manager.activate(name)
    if result.get("needs_choice"):
        selected = _choose_candidate(manager, f"Which {name}?", result.get("candidates") or [], choose)
        if selected is None:
            return str(result.get("message") or "This name is ambiguous.")
        result = manager.activate(str(selected.get("slug") or selected.get("name")))
    return str(result.get("message") or "")


def _handle_load_personas(
    rest: str,
    progress: Optional[Callable[[str], None]] = None,
) -> str:
    from core.persona_market import MarketError, get_persona_market

    market = get_persona_market()
    tokens = (rest or "").split()
    lowered = [token.lower() for token in tokens]
    if not tokens:
        return market.format_catalog()
    if lowered[0] in ("help", "-h", "--help"):
        return PERSONAS_HELP

    force = any(token in ("--force", "-f") for token in lowered)
    install_all = any(token in ("--all", "all") for token in lowered)
    refresh = any(token in ("refresh", "update", "--refresh") for token in lowered)
    flags = {"--force", "-f", "--all", "all", "refresh", "update", "--refresh"}
    selector = " ".join(token for token in tokens if token.lower() not in flags).strip()
    first = lowered[0]

    try:
        if first in ("list", "ls", "available", "market"):
            if progress:
                progress("Fetching persona market...")
            return market.format_catalog(refresh=refresh)
        if first in ("refresh", "update", "--refresh"):
            if progress:
                progress("Refreshing persona market...")
            return market.format_catalog(refresh=True)
        if first in ("search", "find"):
            query = " ".join(tokens[1:]).strip()
            if not query:
                return "Usage: /load-personas search <text>"
            if progress:
                progress("Searching persona market...")
            results = market.search(query, refresh=refresh)
            if not results:
                return "No personas match " + repr(query) + "."
            lines = ["Persona market matches for " + repr(query) + ":", ""]
            for entry in results:
                status = (
                    "installed"
                    if entry.get("current")
                    else ("update available" if entry.get("update_available") else "available")
                )
                lines.append(f"{entry['number']:>2}. {entry.get('display_name') or entry.get('name')}  [{status}]")
                description = str(entry.get("description") or "").strip()
                if description:
                    lines.append("    " + description[:140])
            lines.extend(["", "Install: /load-personas <number|name>"])
            return "\n".join(lines)
        if install_all:
            if progress:
                progress("Installing persona market...")
            results = market.install_all(force=force, refresh=refresh)
            lines = ["Persona market install results:", ""]
            for result in results:
                status = "SKIP" if result.get("skipped") else ("OK" if result.get("ok") else "FAILED")
                lines.append(status + "  " + str(result.get("slug") or "") + "  " + str(result.get("message") or ""))
            return "\n".join(lines)
        if first in ("install", "add", "get"):
            selector = " ".join(tokens[1:]).strip()
            if not selector:
                return "Usage: /load-personas <number|name>  (use /load-personas to list)"
        if not selector:
            return PERSONAS_HELP
        if progress:
            progress("Installing " + selector + " from persona market...")
        result = market.install(selector, force=force, refresh=refresh)
        return str(result.get("message") or "Persona installed.")
    except MarketError as exc:
        return "Persona market: " + str(exc)


def _handle_memory(rest: str) -> str:
    store = _memory_store()
    if not rest:
        return store.summary()

    parts = rest.split(None, 1)
    action = parts[0].lower()
    tail = parts[1].strip() if len(parts) > 1 else ""

    if action in ("help", "-h", "--help"):
        return MEMORY_HELP
    if action in ("list", "show", "facts", "all"):
        return store.summary()
    if action in ("path", "paths", "files"):
        return (
            f"Store:   {store.profile_path}\n"
            f"Readable: {store.markdown_path}\n"
            f"Events:  {store.events_path}\n"
            f"Folder:  {store.root}"
        )
    if action in ("search", "find"):
        if not tail:
            return "Usage: /memory search <query>"
        results = store.search(tail)
        if not results:
            return f"Nothing remembered about '{tail}'."
        return "\n".join(f"- {fact.get('key')}: {fact.get('value')}" for fact in results)
    if action in ("forget", "remove", "delete", "rm"):
        if not tail:
            return "Usage: /memory forget <key>  (see /memory list for keys)"
        if store.forget(tail):
            return f"Forgotten: {tail}"
        return f"No fact with key '{tail}'."
    if action in ("clear", "wipe", "reset"):
        store.clear()
        return "User memory cleared. Collig will start learning you again from this point."
    if action == "note":
        if not tail:
            return "Usage: /memory note <text>"
        from core.user_memory import extract_heuristics, looks_sensitive, normalize_key

        stored = []
        for fact in extract_heuristics(tail):
            saved = store.upsert_fact(
                fact["key"],
                fact["value"],
                category=fact["category"],
                confidence=fact["confidence"],
                source="explicit",
                evidence="Explicitly saved with /memory note",
            )
            if saved:
                stored.append(saved["key"])
        if not stored:
            # A note the user typed is stored even when it looks like a
            # secret (password, token, ...).  Warn, but never drop it.
            saved = store.upsert_fact(
                "note_" + normalize_key(tail)[:40],
                tail,
                category="other",
                confidence=0.95,
                source="explicit",
                evidence="Explicitly saved with /memory note",
                allow_sensitive=True,
            )
            if saved is None:
                return "That note was empty, so it was not stored."
            stored.append(saved["key"])
        warning = (
            " Warning: it looks like it contains a password or other secret; it is stored in plain text."
            if looks_sensitive(tail)
            else ""
        )
        return "Noted: " + tail + " (keys: " + ", ".join(stored) + ")" + warning
    if action in ("on", "off"):
        error = _set_config(USER_MEMORY_ENABLED=(action == "on"))
        if error:
            return error
        return f"User memory {'enabled' if action == 'on' else 'disabled'}. " + (
            "" if action == "on" else "Existing facts are kept but no longer used."
        )
    if action in ("proactive", "routines"):
        sub = tail.lower()
        if sub not in ("on", "off"):
            return "Usage: /memory proactive on|off"
        error = _set_config(USER_MEMORY_PROACTIVE=(sub == "on"))
        if error:
            return error
        return f"Proactive routines {'enabled' if sub == 'on' else 'disabled'}."
    if action in ("extract", "auto", "llm"):
        sub = tail.lower()
        if sub not in ("on", "off"):
            return "Usage: /memory extract on|off"
        error = _set_config(USER_MEMORY_LLM_EXTRACT=(sub == "on"))
        if error:
            return error
        return (
            f"Background LLM extraction {'enabled' if sub == 'on' else 'disabled'}. "
            "Rule-based capture is unaffected."
        )
    return MEMORY_HELP


def handle_slash_command(
    text: str,
    *,
    progress: Optional[Callable[[str], None]] = None,
    choose: Optional[Callable[..., Optional[int]]] = None,
) -> Optional[str]:
    """
    Run a meta command, or return ``None`` when ``text`` is not one.

    ``text`` may include the leading slash (web chat) or not (the CLI strips it
    before dispatch).
    """
    split = _split_command(text)
    if split is None:
        return None
    command, rest = split
    if command == "distill":
        return _handle_distill(rest, progress, choose)
    if command == "chatto":
        return _handle_chatto(rest, choose)
    if command == "personality":
        return _handle_personality(rest, choose)
    if command == "memory":
        return _handle_memory(rest)
    if command in ("load-personas", "personas"):
        return _handle_load_personas(rest, progress)
    return None


def is_meta_command(text: str) -> bool:
    split = _split_command(text)
    return split is not None
