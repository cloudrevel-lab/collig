"""
Provider-scoped configuration UI for the Collig CLI.

The old /config screen was one flat list containing every provider's key,
endpoint and model at once, so selecting DeepSeek still showed DashScope rows.
This module implements a two-level screen stack:

    Root -> Model Provider -> one provider's own settings

Escape walks back one level and only quits from the root.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from prompt_toolkit import Application
from prompt_toolkit.formatted_text import to_formatted_text
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window, WindowAlign
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.shortcuts import prompt
from rich.console import Console
from rich.prompt import Confirm

from core.runtime import (
    _PROVIDER_BASE_URLS,
    cache_available_models,
    default_model_for,
    fetch_provider_models,
    get_base_url_choices,
    load_config,
    remember_base_url,
    save_config,
    set_llm_field,
)

console = Console()


@dataclass(frozen=True)
class ProviderProfile:
    key: str
    label: str
    tagline: str
    key_field: Optional[str] = None
    key_label: str = "API Key"
    needs_key: bool = True
    models: Tuple[str, ...] = ()
    kind: str = "hosted"


PROFILES: Dict[str, ProviderProfile] = {
    "openai": ProviderProfile(
        "openai",
        "OpenAI",
        "Official OpenAI API",
        "OPENAI_API_KEY",
        "OpenAI API Key",
        True,
        ("gpt-4o", "gpt-4o-mini", "o3-mini", "gpt-4.1"),
    ),
    "deepseek": ProviderProfile(
        "deepseek",
        "DeepSeek",
        "DeepSeek V3 / R1, OpenAI-compatible",
        "DEEPSEEK_API_KEY",
        "DeepSeek API Key",
        True,
        ("deepseek-chat", "deepseek-reasoner"),
    ),
    "dashscope": ProviderProfile(
        "dashscope",
        "DashScope (Qwen)",
        "Alibaba Cloud Qwen models",
        "DASHSCOPE_API_KEY",
        "DashScope API Key",
        True,
        ("qwen-plus", "qwen-max", "qwen-turbo", "qwen-long"),
        "dashscope",
    ),
    "ollama": ProviderProfile(
        "ollama",
        "Ollama",
        "Local Ollama server",
        None,
        "",
        False,
        ("qwen3:8b", "llama3.1", "mistral"),
        "local",
    ),
    "llama": ProviderProfile(
        "llama",
        "Llama.cpp / Local",
        "Local llama.cpp or Ollama-compatible server",
        None,
        "",
        False,
        ("llama3.1", "codellama"),
        "local",
    ),
    "custom": ProviderProfile(
        "custom",
        "Custom / Gateway",
        "Any OpenAI-compatible endpoint",
        "CUSTOM_API_KEY",
        "Endpoint API Key (optional)",
        False,
        (),
        "custom",
    ),
}

PROVIDER_ORDER = ["openai", "deepseek", "dashscope", "ollama", "llama", "custom"]

DASHSCOPE_REGIONS = {
    "china": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "singapore": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "international": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
}


def _model_key(provider: str) -> str:
    return provider.upper() + "_MODEL"


def _url_key(provider: str) -> str:
    return provider.upper() + "_URL"


def _models_key(provider: str) -> str:
    return provider.upper() + "_AVAILABLE_MODELS"


def _active_provider(config: Dict[str, Any]) -> str:
    return str(config.get("provider") or config.get("LLM_PROVIDER") or "openai").lower()


def _mask(value: str) -> str:
    value = str(value or "")
    if not value:
        return "(not set)"
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * 6 + value[-2:]


def _region_for(config: Dict[str, Any]) -> str:
    raw = str(config.get("DASHSCOPE_ENDPOINT") or "china").strip()
    if raw.startswith("http"):
        for region, url in DASHSCOPE_REGIONS.items():
            if raw.rstrip("/") == url.rstrip("/"):
                return region
        return "china"
    region = raw.lower()
    return region if region in DASHSCOPE_REGIONS else "china"


def provider_view(provider: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the detail screen needs for one provider, scoped to it."""
    provider = provider.lower()
    profile = PROFILES[provider]
    active = _active_provider(config) == provider

    key = ""
    if profile.key_field:
        key = str(config.get(profile.key_field) or "")
        if not key and active:
            key = str(config.get("api_key") or "")

    region = _region_for(config) if provider == "dashscope" else ""

    if provider == "custom":
        url = str(config.get("CUSTOM_BASE_URL") or "")
        if not url and active:
            url = str(config.get("provider_url") or "")
    elif provider == "dashscope":
        url = str(config.get(_url_key(provider)) or DASHSCOPE_REGIONS[region])
    else:
        url = str(config.get(_url_key(provider)) or "")
        if not url and active:
            url = str(config.get("provider_url") or "")
        if not url:
            url = _PROVIDER_BASE_URLS.get(provider, "")

    model = str(config.get(_model_key(provider)) or "")
    if not model and active:
        model = str(config.get("llm_model") or config.get("LLM_MODEL") or "")
    if not model:
        model = profile.models[0] if profile.models else default_model_for(provider)

    raw_models = config.get(_models_key(provider))
    if not isinstance(raw_models, list) or not raw_models:
        raw_models = (config.get("available_models") or []) if active else []
    models: List[str] = []
    for item in raw_models or []:
        name = item.get("id") if isinstance(item, dict) else item
        if name and str(name) not in models:
            models.append(str(name))

    return {
        "provider": provider,
        "profile": profile,
        "active": active,
        "key": key,
        "url": url,
        "region": region,
        "model": model,
        "available_models": models,
    }


def set_provider_field(config: Dict[str, Any], provider: str, field_name: str, value: Any) -> None:
    """Write one provider-scoped field without leaking it into other providers."""
    provider = provider.lower()
    profile = PROFILES[provider]
    active = _active_provider(config) == provider

    if field_name == "key":
        if profile.key_field:
            config[profile.key_field] = value or ""
        if active:
            set_llm_field(config, "api_key", value or "")
        return
    if field_name == "region":
        config["DASHSCOPE_ENDPOINT"] = value or "china"
        if active:
            config.pop("provider_url", None)
        return
    if field_name == "url":
        if provider == "custom":
            config["CUSTOM_BASE_URL"] = value or ""
        else:
            config[_url_key(provider)] = value or ""
        if active:
            set_llm_field(config, "provider_url", value or "")
        return
    if field_name == "model":
        config[_model_key(provider)] = value or ""
        if active:
            set_llm_field(config, "llm_model", value or "")
        return
    if field_name == "available_models":
        models = list(value or [])
        config[_models_key(provider)] = models
        if active:
            set_llm_field(config, "available_models", models)
        return


@dataclass
class Row:
    key: str
    label: str
    value: str = ""
    kind: str = "string"
    detail: str = ""
    choices: List[str] = field(default_factory=list)


@dataclass
class ConfigState:
    config: Dict[str, Any]
    agent: Any = None
    active: str = "openai"
    pending: str = "openai"
    screen: str = "root"
    index: int = 0
    selected_provider: str = ""
    dirty: bool = False
    status: str = ""

    def __post_init__(self):
        self.active = _active_provider(self.config)
        self.pending = self.active

    def _skills(self) -> List[Any]:
        if self.agent is None:
            return []
        try:
            return list(self.agent.skill_manager.skills)
        except Exception:
            return []

    def root_rows(self) -> List[Row]:
        view = provider_view(self.pending, self.config)
        skills = self._skills()
        enabled = sum(1 for s in skills if s.enabled)
        jira_email = str(self.config.get("JIRA_EMAIL") or "")
        thinking = "on" if self.config.get("VERBOSE_THINKING", True) else "off"
        markdown = "on" if self.config.get("ENABLE_MARKDOWN", True) else "off"
        maps = "set" if self.config.get("google_maps_api_key") else "not set"
        return [
            Row(
                "provider",
                "Model Provider",
                f"{view['profile'].label} / {view['model']}" + ("" if self.pending == self.active else "  (unsaved)"),
                "action",
                "Choose a provider; only its own settings are shown",
            ),
            Row("appearance", "Appearance & Behaviour", f"thinking {thinking} / markdown {markdown}", "action"),
            Row("other", "Other API Keys", f"Google Maps: {maps}", "action"),
            Row("jira", "Jira Integration", jira_email or "not configured", "action"),
            Row("skills", "Skills", f"{enabled}/{len(skills)} enabled", "action"),
            Row("save_exit", "Save & Exit", "write config.json and update the live agent", "action"),
            Row("quit", "Exit without Saving", "", "action"),
        ]

    def provider_rows(self) -> List[Row]:
        rows = []
        for key in PROVIDER_ORDER:
            profile = PROFILES[key]
            view = provider_view(key, self.config)
            marks = []
            if key == self.active:
                marks.append("active")
            if key == self.pending and key != self.active:
                marks.append("selected")
            if profile.key_field:
                if view["key"]:
                    marks.append("key set")
                elif profile.needs_key:
                    marks.append("no key")
            rows.append(Row(key, profile.label, f"{view['model']}  [{' / '.join(marks)}]", "action", profile.tagline))
        rows.append(Row("back", "Back", "return to the main menu", "action"))
        return rows

    def detail_rows(self) -> List[Row]:
        provider = self.selected_provider or self.pending
        profile = PROFILES[provider]
        view = provider_view(provider, self.config)
        rows: List[Row] = []
        if profile.key_field:
            rows.append(Row("key", profile.key_label, _mask(view["key"]), "secret", profile.key_field or ""))
        if provider == "dashscope":
            rows.append(
                Row(
                    "region",
                    "DashScope Region",
                    view["region"],
                    "choice",
                    "china / singapore / international",
                    ["china", "singapore", "international"],
                )
            )
            rows.append(Row("url_info", "Endpoint", view["url"], "info", "derived from the selected region"))
        else:
            choices = [str(c.get("url")) for c in get_base_url_choices(provider, self.config) if c.get("url")]
            rows.append(
                Row("url", "Base URL", view["url"], "string", "press Enter to edit; presets are listed below", choices)
            )
        rows.append(
            Row("model", "Model", view["model"], "string", "press Enter to edit, or [m] to fetch the live list")
        )
        if view["available_models"]:
            rows.append(
                Row(
                    "models",
                    "Cached Models",
                    f"{len(view['available_models'])} available",
                    "info",
                    "press [m] to refresh",
                )
            )
        rows.append(Row("fetch", "Fetch Models from Provider", "", "action", "queries the provider's /models endpoint"))
        rows.append(Row("back", "Back", "return to the provider list", "action"))
        return rows

    def ui_rows(self) -> List[Row]:
        return [
            Row(
                "VERBOSE_THINKING",
                "Verbose Thinking",
                "ON" if self.config.get("VERBOSE_THINKING", True) else "OFF",
                "boolean",
            ),
            Row(
                "ENABLE_MARKDOWN",
                "Enable Markdown",
                "ON" if self.config.get("ENABLE_MARKDOWN", True) else "OFF",
                "boolean",
            ),
            Row("back", "Back", "return to the main menu", "action"),
        ]

    def other_rows(self) -> List[Row]:
        return [
            Row(
                "google_maps_api_key",
                "Google Maps API Key",
                _mask(self.config.get("google_maps_api_key") or ""),
                "secret",
            ),
            Row("back", "Back", "return to the main menu", "action"),
        ]

    def jira_rows(self) -> List[Row]:
        return [
            Row("JIRA_EMAIL", "Jira Email", str(self.config.get("JIRA_EMAIL") or "(not set)"), "string"),
            Row("JIRA_API_TOKEN", "Jira API Token", _mask(self.config.get("JIRA_API_TOKEN") or ""), "secret"),
            Row("back", "Back", "return to the main menu", "action"),
        ]

    def skill_rows(self) -> List[Row]:
        rows = []
        for skill in self._skills():
            try:
                count = len(skill.tool_metadata())
            except Exception:
                count = 0
            rows.append(
                Row(
                    "skill:" + skill.name,
                    skill.name,
                    f"{'ON' if skill.enabled else 'OFF'} / {count} tool" + ("s" if count != 1 else ""),
                    "skill",
                    getattr(skill, "description", "") or "",
                )
            )
        rows.append(Row("back", "Back", "return to the main menu", "action"))
        return rows

    def rows(self) -> List[Row]:
        return {
            "root": self.root_rows,
            "providers": self.provider_rows,
            "detail": self.detail_rows,
            "ui": self.ui_rows,
            "other": self.other_rows,
            "jira": self.jira_rows,
            "skills": self.skill_rows,
        }.get(self.screen, self.root_rows)()

    def current_row(self) -> Optional[Row]:
        rows = self.rows()
        if not rows:
            return None
        self.index = max(0, min(self.index, len(rows) - 1))
        return rows[self.index]

    def reset_index(self) -> None:
        self.index = 0

    def back(self) -> bool:
        if self.screen == "detail":
            self.screen = "providers"
            self.reset_index()
        elif self.screen in ("providers", "ui", "other", "jira", "skills"):
            self.screen = "root"
            self.reset_index()
        else:
            return True
        return False

    def open_provider(self, provider: str) -> None:
        self.selected_provider = provider
        self.pending = provider
        self.screen = "detail"
        self.reset_index()

    def toggle_row(self, row: Row) -> None:
        if row.kind == "boolean":
            self.config[row.key] = not self.config.get(row.key, True)
            self.dirty = True
        elif row.kind == "skill" and row.key.startswith("skill:"):
            name = row.key.split(":", 1)[1]
            for skill in self._skills():
                if skill.name == name:
                    skill.enabled = not skill.enabled
                    key = "SKILL_" + name.upper().replace(" ", "_") + "_ENABLED"
                    self.config[key] = skill.enabled
                    self.dirty = True
                    break

    def cycle_row(self, row: Row, direction: int) -> None:
        if row.kind == "choice" and row.choices:
            try:
                idx = row.choices.index(row.value)
            except ValueError:
                idx = 0
            value = row.choices[(idx + direction) % len(row.choices)]
            if self.screen == "detail" and row.key == "region":
                set_provider_field(self.config, self.selected_provider, "region", value)
                self.dirty = True
        elif row.kind == "boolean":
            self.toggle_row(row)

    def save(self) -> None:
        for provider in PROVIDER_ORDER:
            view = provider_view(provider, self.config)
            profile = PROFILES[provider]
            if profile.key_field:
                self.config[profile.key_field] = view["key"]
            if provider == "custom":
                self.config["CUSTOM_BASE_URL"] = view["url"]
            elif provider == "dashscope":
                self.config["DASHSCOPE_ENDPOINT"] = view["region"]
                self.config[_url_key(provider)] = view["url"]
            else:
                self.config[_url_key(provider)] = view["url"]
            self.config[_model_key(provider)] = view["model"]
            self.config[_models_key(provider)] = list(view["available_models"])
            if view["url"]:
                remember_base_url(provider, view["url"], self.config, save=False)

        provider = self.pending
        view = provider_view(provider, self.config)
        set_llm_field(self.config, "provider", provider)
        set_llm_field(self.config, "llm_model", view["model"])
        if PROFILES[provider].key_field and view["key"]:
            set_llm_field(self.config, "api_key", view["key"])
        if provider == "dashscope":
            self.config.pop("provider_url", None)
        else:
            set_llm_field(self.config, "provider_url", view["url"])
        if view["available_models"]:
            set_llm_field(self.config, "available_models", view["available_models"])
        save_config(self.config)

        try:
            from dotenv import set_key as _set_key
        except Exception:
            _set_key = None
        for profile in PROFILES.values():
            if not profile.key_field:
                continue
            value = self.config.get(profile.key_field)
            if not value:
                continue
            os.environ[profile.key_field] = str(value)
            try:
                if _set_key is not None and os.path.exists(".env"):
                    _set_key(".env", profile.key_field, str(value))
            except Exception:
                pass

        if self.agent is not None:
            try:
                self.agent.set_provider(provider, view["model"])
            except Exception as exc:
                self.status = f"Saved, but live switch failed: {exc}"
                self.dirty = False
                return
        self.active = provider
        self.dirty = False
        self.status = f"Saved. Active: {PROFILES[provider].label} / {view['model']}"

    def confirm_quit(self) -> bool:
        if not self.dirty:
            return True
        return Confirm.ask("You have unsaved changes. Save before quitting?", default=True)

    def header_text(self) -> List[Tuple[str, str]]:
        parts: List[Tuple[str, str]] = [("bold", "Collig Configuration\n\n")]
        if self.status:
            parts.append(("bold green", f"  {self.status}\n\n"))
        if self.screen == "root":
            parts.append(("dim", "  Provider-scoped settings. Escape goes back; q quits.\n\n"))
        elif self.screen == "providers":
            parts.append(("bold cyan", "  Model Provider\n"))
            parts.append(("dim", "  The next screen shows only the selected provider's fields.\n\n"))
        elif self.screen == "detail":
            profile = PROFILES[self.selected_provider]
            mark = "active" if self.selected_provider == self.active else "selected (not yet saved)"
            parts.append(("bold cyan", f"  {profile.label}\n"))
            parts.append(("dim", f"  {profile.tagline} / {mark}\n\n"))
        elif self.screen == "skills":
            parts.append(("bold cyan", "  Skills\n"))
            parts.append(("dim", "  Disabled skills are never offered to the model.\n\n"))
        elif self.screen == "ui":
            parts.append(("bold cyan", "  Appearance & Behaviour\n\n"))
        elif self.screen == "other":
            parts.append(("bold cyan", "  Other API Keys\n\n"))
        elif self.screen == "jira":
            parts.append(("bold cyan", "  Jira Integration\n\n"))
        return parts

    def content_text(self):
        rows = self.rows()
        self.index = max(0, min(self.index, len(rows) - 1)) if rows else 0
        parts = self.header_text()
        for i, row in enumerate(rows):
            selected = i == self.index
            parts.append(("bold cyan" if selected else "", f"{'> ' if selected else '  '}{row.label}: "))
            parts.append(("bold reverse" if selected else "", f" {row.value} " if row.value else ""))
            if row.detail:
                parts.append(("dim", f"  {row.detail}"))
            parts.append(("", "\n"))
        return to_formatted_text(parts)

    def footer_text(self):
        if self.screen == "detail":
            hint = "[up/down] Navigate  [Enter] Edit  [left/right] Toggle  [m] Models  [s] Save  [Esc] Back  [q] Quit"
        elif self.screen == "skills":
            hint = "[up/down] Navigate  [Space] Toggle  [s] Save  [Esc] Back  [q] Quit"
        elif self.screen == "root":
            hint = "[up/down] Navigate  [Enter] Open  [s] Save  [Esc] Quit  [q] Quit"
        else:
            hint = "[up/down] Navigate  [Enter] Open  [left/right] Toggle  [s] Save  [Esc] Back  [q] Quit"
        return to_formatted_text([("dim", hint)])


def _edit_row(state: ConfigState, row: Row) -> None:
    provider = state.selected_provider or state.pending
    if row.kind not in ("string", "secret"):
        return
    if row.kind == "secret":
        current = ""
        note = "type a new value, or leave blank to keep the current one"
    else:
        current = row.value
        note = "press Enter to keep, type to replace"
    try:
        console.print(f"[dim]Editing {row.label} ({note}):[/dim]")
        value = prompt(f"{row.label} = ", default=current, is_password=(row.kind == "secret"))
    except (KeyboardInterrupt, EOFError):
        console.print("[dim]Edit cancelled.[/dim]")
        return
    if value is None:
        return
    if row.kind == "secret" and not value:
        return
    if row.key in ("key", "url", "model"):
        set_provider_field(state.config, provider, row.key, value)
    else:
        state.config[row.key] = value
    state.dirty = True
    state.status = f"{row.label} updated (press s to save)"


def _fetch_models(state: ConfigState) -> None:
    provider = state.selected_provider or state.pending
    view = provider_view(provider, state.config)
    console.print(f"[dim]Fetching models for {PROFILES[provider].label}...[/dim]")
    try:
        models = fetch_provider_models(
            provider,
            state.config,
            refresh=True,
            override_base_url=view["url"] or None,
            override_api_key=view["key"] or None,
        )
    except Exception as exc:
        state.status = f"Could not fetch models: {exc}"
        return
    names: List[str] = []
    for item in models or []:
        name = item.get("id") if isinstance(item, dict) else item
        if name and str(name) not in names:
            names.append(str(name))
    if not names:
        state.status = "Provider returned no models."
        return
    try:
        from core.cli import interactive_menu

        default = names.index(view["model"]) if view["model"] in names else 0
        choice = interactive_menu(
            f"Select a model for {PROFILES[provider].label} (Enter to choose, Esc to cancel)",
            names,
            default,
        )
    except Exception:
        console.print("[dim]Model list:[/dim]")
        for i, name in enumerate(names[:40], 1):
            console.print(f"  {i}. {name}")
        try:
            raw = console.input("[bold]Model number or name:[/bold] ").strip()
        except (KeyboardInterrupt, EOFError):
            return
        if not raw:
            return
        if raw.isdigit() and 1 <= int(raw) <= len(names):
            choice = int(raw) - 1
        elif raw in names:
            choice = names.index(raw)
        else:
            choice = -1
    if choice is None or choice < 0 or choice >= len(names):
        state.status = "Model selection cancelled."
        return
    selected = names[choice]
    try:
        cache_available_models(provider, models, state.config, persist=False)
        state.config[_models_key(provider)] = list(models)
    except Exception:
        pass
    set_provider_field(state.config, provider, "model", selected)
    state.dirty = True
    state.status = f"Model set to {selected} (press s to save)"


def run_config_ui(agent: Any = None) -> None:
    """Entry point used by the CLI /config command."""
    state = ConfigState(config=load_config(), agent=agent)
    while True:
        rows = state.rows()
        if not rows:
            return
        state.index = max(0, min(state.index, len(rows) - 1))
        content_control = FormattedTextControl(text=state.content_text())
        footer_control = FormattedTextControl(text=state.footer_text())
        tabs_control = FormattedTextControl(text=to_formatted_text([("bold", " Settings ")]))
        layout = Layout(
            HSplit(
                [
                    Window(content=tabs_control, height=1, align=WindowAlign.LEFT),
                    Window(
                        content=content_control,
                        width=Dimension(min=70, preferred=92),
                        height=Dimension(min=18, preferred=28),
                        align=WindowAlign.LEFT,
                    ),
                    Window(content=footer_control, height=1),
                ]
            )
        )

        kb = KeyBindings()

        def refresh() -> None:
            content_control.text = state.content_text()
            footer_control.text = state.footer_text()

        @kb.add("up")
        def _up(event):
            state.index = (state.index - 1) % len(state.rows())
            refresh()

        @kb.add("down")
        def _down(event):
            state.index = (state.index + 1) % len(state.rows())
            refresh()

        @kb.add("left")
        def _left(event):
            row = state.current_row()
            if row:
                state.cycle_row(row, -1)
                refresh()

        @kb.add("right")
        def _right(event):
            row = state.current_row()
            if row:
                state.cycle_row(row, 1)
                refresh()

        @kb.add("space")
        def _space(event):
            row = state.current_row()
            if row:
                state.toggle_row(row)
                refresh()

        @kb.add("enter")
        def _enter(event):
            row = state.current_row()
            if row is None:
                return
            if row.kind in ("string", "secret"):
                event.app.exit(result=("edit", row))
                return
            if row.kind in ("skill", "boolean"):
                state.toggle_row(row)
                refresh()
                return
            if row.key == "provider":
                state.screen = "providers"
                state.reset_index()
            elif row.key == "back":
                if state.back():
                    event.app.exit(result=("quit",))
                    return
            elif row.key in PROVIDER_ORDER and state.screen == "providers":
                state.open_provider(row.key)
            elif row.key == "appearance":
                state.screen = "ui"
                state.reset_index()
            elif row.key == "other":
                state.screen = "other"
                state.reset_index()
            elif row.key == "jira":
                state.screen = "jira"
                state.reset_index()
            elif row.key == "skills":
                state.screen = "skills"
                state.reset_index()
            elif row.key == "fetch":
                event.app.exit(result=("fetch",))
                return
            elif row.key == "save_exit":
                event.app.exit(result=("save_exit",))
                return
            elif row.key == "quit":
                event.app.exit(result=("quit_nosave",))
                return
            refresh()

        @kb.add("m")
        def _fetch(event):
            if state.screen == "detail":
                event.app.exit(result=("fetch",))

        @kb.add("s")
        def _save(event):
            event.app.exit(result=("save",))

        @kb.add("escape")
        def _escape(event):
            if state.screen == "root":
                event.app.exit(result=("quit",))
                return
            if state.back():
                event.app.exit(result=("quit",))
                return
            refresh()

        @kb.add("q")
        @kb.add("c-c")
        def _quit(event):
            event.app.exit(result=("quit",))

        app = Application(layout=layout, key_bindings=kb, full_screen=False)
        result = app.run()
        if not result:
            break
        kind = result[0]
        if kind == "edit":
            _edit_row(state, result[1])
            continue
        if kind == "fetch":
            _fetch_models(state)
            continue
        if kind == "save":
            state.save()
            continue
        if kind == "save_exit":
            state.save()
            break
        if kind == "quit_nosave":
            break
        if kind == "quit":
            if state.dirty:
                try:
                    if Confirm.ask("You have unsaved changes. Save before quitting?", default=True):
                        state.save()
                except (KeyboardInterrupt, EOFError):
                    pass
            break
