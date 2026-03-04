import os
import sys

# Add parent directory to sys.path to allow importing 'skills' from sibling directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import argparse
import json
import zipfile
import shutil
import time
from datetime import datetime
from rich.console import Console
from rich.live import Live
from rich.text import Text
from rich.prompt import Prompt as RichPrompt, Confirm
from rich.markdown import Markdown
from rich.panel import Panel
from dotenv import load_dotenv, set_key
from core.paths import paths

# Import prompt_toolkit for advanced input handling
from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML, to_formatted_text
from prompt_toolkit.shortcuts import prompt
from prompt_toolkit.key_binding import KeyBindings

class SkillCommandCompleter(Completer):
    def __init__(self, agent):
        self.agent = agent

    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor

        # Only trigger if it starts with /
        if not text.startswith("/"):
            return

        # Get the command part (remove /)
        cmd = text[1:].lower()

        # Built-in commands
        commands = [
            ("config", "Interactive configuration manager"),
            ("config list", "Show current configuration"),
            ("config set", "Set a configuration value"),
            ("backup", "Backup user data to a zip file"),
            ("restore", "Restore user data from a zip file"),
            ("provider", "Switch LLM provider (openai/ollama/llama/deepseek)"),
            ("news", "Open interactive news browser (if news was searched)"),
            ("status", "Check system status and LLM connection"),
            ("stats", "Show token usage statistics (session + overall)"),
            ("stats session", "Show token usage for current session"),
            ("stats overall", "Show overall token usage across all sessions"),
            ("doctor", "Check system health and LLM connection"),
            ("test", "Alias for doctor"),
            ("run", "Run a shell command (e.g., /run ls -la)"),
            ("restart", "Restart the session (reload code)"),
            ("quiet", "Hide thinking messages"),
            ("verbose", "Show thinking messages"),
            ("toggle thinking", "Toggle thinking messages visibility"),
            ("toggle markdown", "Toggle markdown rendering"),
            ("exit", "Exit the application"),
            ("quit", "Exit the application"),
            ("clear", "Clear the screen")
        ]

        # Add skill tools
        if hasattr(self.agent, 'tools'):
            for tool in self.agent.tools:
                commands.append((tool.name, f"Tool: {tool.description}"))

        # Track seen commands to avoid duplicates if logic changes
        seen = set()

        # 1. Yield exact/prefix matches first (Better UX)
        for command, description in commands:
            if command.lower().startswith(cmd):
                seen.add(command)
                yield Completion(command, start_position=-len(cmd), display=command, display_meta=description)

        # 2. Yield substring matches
        for command, description in commands:
            if cmd in command.lower() and command not in seen:
                yield Completion(command, start_position=-len(cmd), display=command, display_meta=description)

# Load environment variables
load_dotenv()

# Use paths.global_config_file instead of local config.json
CONFIG_FILE = paths.global_config_file

# Global markdown preference (will be initialized after config loading)
ENABLE_MARKDOWN = True

# Configure console with better markdown support
console = Console(force_terminal=True, color_system="truecolor")


def interactive_menu(title: str, options: list, default_index: int = 0) -> int:
    """
    Display an interactive menu with arrow key navigation.

    Args:
        title: The menu title/prompt
        options: List of option strings to display
        default_index: The initially selected option index

    Returns:
        The index of the selected option, or -1 if cancelled
    """
    from prompt_toolkit import Application
    from prompt_toolkit.layout import Layout, HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.key_binding import KeyBindings

    selected_index = default_index

    def get_menu_text():
        result = []
        result.append(("bold", f"{title}\n\n"))
        for i, option in enumerate(options):
            if i == selected_index:
                result.append(("bold cyan", f" > {option}\n"))
            else:
                result.append(("", f"   {option}\n"))
        result.append(("", "\n[↑/↓] Navigate  [Enter] Select  [Esc] Cancel"))
        return to_formatted_text(result)

    kb = KeyBindings()

    @kb.add("up")
    def move_up(event):
        nonlocal selected_index
        selected_index = (selected_index - 1) % len(options)
        menu_control.text = get_menu_text()

    @kb.add("down")
    def move_down(event):
        nonlocal selected_index
        selected_index = (selected_index + 1) % len(options)
        menu_control.text = get_menu_text()

    @kb.add("enter")
    def select(event):
        event.app.exit(result=selected_index)

    @kb.add("escape")
    def cancel(event):
        event.app.exit(result=-1)

    @kb.add("c-c")
    def ctrl_c(event):
        event.app.exit(result=-1)

    menu_control = FormattedTextControl(text=get_menu_text())
    window = Window(content=menu_control, width=Dimension(min=40), height=Dimension(min=len(options) + 5))

    layout = Layout(HSplit([window]))
    app = Application(layout=layout, key_bindings=kb, full_screen=False)

    try:
        result = app.run()
        return result
    except:
        return -1


def interactive_select(title: str, options: list, default_index: int = 0) -> str:
    """
    Display an interactive menu and return the selected option text.

    Args:
        title: The menu title/prompt
        options: List of option strings to display
        default_index: The initially selected option index

    Returns:
        The selected option string, or None if cancelled
    """
    try:
        idx = interactive_menu(title, options, default_index)
        if idx >= 0 and idx < len(options):
            return options[idx]
        return None
    except Exception as e:
        # Fallback to simple prompt if menu fails
        console.print(f"[dim]Interactive menu failed, using simple selection.[/dim]")
        for i, opt in enumerate(options):
            console.print(f"  {i+1}. {opt}")
        choice = console.input("[bold]Select an option (number):[/bold] ")
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return options[idx]
        except:
            pass
        return options[0] if options else None


# Global reference to news cache access functions
_news_functions = None

def set_news_functions(get_cache_func, get_query_func):
    """Set the news functions from the NewsSkill."""
    global _news_functions
    _news_functions = {
        "get_cache": get_cache_func,
        "get_query": get_query_func
    }


def interactive_news_menu(news_items: list, query: str = "") -> dict:
    """
    Display an interactive news menu with navigation and actions.

    Args:
        news_items: List of news item dicts from DDGS
        query: The original search query

    Returns:
        Dict with action type and data, or None if cancelled
    """
    from prompt_toolkit import Application
    from prompt_toolkit.layout import Layout, HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.key_binding import KeyBindings

    if not news_items:
        return None

    selected_index = 0
    mode = "list"  # "list" or "detail"

    def truncate_text(text: str, max_len: int = 60) -> str:
        if not text:
            return ""
        return text[:max_len] + "..." if len(text) > max_len else text

    def get_list_text():
        result = []
        result.append(("bold cyan", "📰 News Browser"))
        if query:
            result.append(("", f" - {query}\n\n"))
        else:
            result.append(("", "\n\n"))

        for i, item in enumerate(news_items):
            title = item.get('title', 'No Title')
            source = item.get('source', 'Unknown')
            date = item.get('date', '')

            display_title = truncate_text(title, 55)
            prefix = " > " if i == selected_index else "   "

            if i == selected_index:
                result.append(("bold reverse", f"{prefix}{i+1}. [{source}] {display_title}"))
                if date:
                    result.append(("dim", f" ({date})"))
                result.append(("", "\n"))
            else:
                line = f"{prefix}{i+1}. [{source}] {display_title}"
                if date:
                    line += f" ({date})"
                result.append(("", line + "\n"))

        result.append(("", "\n"))
        result.append(("dim", "[↑/↓] Navigate  [Enter] Read  [o] Open  [c] Cache All  [Esc] Quit"))
        return to_formatted_text(result)

    def get_detail_text():
        item = news_items[selected_index]
        title = item.get('title', 'No Title')
        body = item.get('body', 'No content available.')
        source = item.get('source', 'Unknown')
        url = item.get('url', '#')
        date = item.get('date', '')

        result = []
        result.append(("bold cyan", f"📰 {title}\n\n"))
        result.append(("dim", f"Source: {source}"))
        if date:
            result.append(("dim", f" | {date}"))
        result.append(("", "\n\n"))
        result.append(("", f"{body}\n\n"))
        result.append(("cyan", f"Link: {url}\n\n"))
        result.append(("dim", "[b] Back  [o] Open in Browser  [Esc] Quit"))
        return to_formatted_text(result)

    kb = KeyBindings()

    @kb.add("up")
    def move_up(event):
        nonlocal selected_index
        if mode == "list":
            selected_index = (selected_index - 1) % len(news_items)
            menu_control.text = get_list_text()

    @kb.add("down")
    def move_down(event):
        nonlocal selected_index
        if mode == "list":
            selected_index = (selected_index + 1) % len(news_items)
            menu_control.text = get_list_text()

    @kb.add("enter")
    def read_item(event):
        nonlocal mode
        if mode == "list":
            mode = "detail"
            menu_control.text = get_detail_text()

    @kb.add("b")
    def back_to_list(event):
        nonlocal mode
        if mode == "detail":
            mode = "list"
            menu_control.text = get_list_text()

    @kb.add("o")
    def open_url(event):
        item = news_items[selected_index]
        url = item.get('url')
        if url and url != '#':
            event.app.exit(result={"action": "open", "url": url, "index": selected_index})
        else:
            console.print("[yellow]No URL available for this item[/yellow]")

    @kb.add("c")
    def cache_list(event):
        event.app.exit(result={"action": "cache_all"})

    @kb.add("escape")
    @kb.add("q")
    def quit(event):
        event.app.exit(result=None)

    @kb.add("c-c")
    def ctrl_c(event):
        event.app.exit(result=None)

    menu_control = FormattedTextControl(text=get_list_text())
    window = Window(
        content=menu_control,
        width=Dimension(min=60, preferred=90),
        height=Dimension(min=15, preferred=25)
    )

    layout = Layout(HSplit([window]))
    app = Application(layout=layout, key_bindings=kb, full_screen=False)

    try:
        result = app.run()
        return result
    except Exception as e:
        console.print(f"[dim]News menu error: {e}[/dim]")
        return None


def handle_news_action(action_result: dict, agent):
    """Handle the action selected from the news menu."""
    if not action_result:
        return

    action = action_result.get("action")

    if action == "open":
        url = action_result.get("url")
        if url:
            import webbrowser
            try:
                webbrowser.open(url)
                console.print(f"[green]Opening: {url}[/green]")
            except Exception as e:
                console.print(f"[red]Failed to open browser: {e}[/red]")

    elif action == "cache_all":
        console.print("[dim]Caching all news items...[/dim]")
        try:
            # Find and call the cache_news_list tool
            for tool in agent.tools:
                if tool.name == "cache_news_list":
                    result = tool.invoke({})
                    console.print(f"[green]{result}[/green]")
                    break
        except Exception as e:
            console.print(f"[red]Failed to cache: {e}[/red]")


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

def handle_backup_command():
    """Backs up user data to a zip file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"collig_backup_{timestamp}.zip"

    # Backup from ~/.collig
    # But wait, the user might expect the zip to be in the current working directory.
    # We should zip the contents of ~/.collig

    source_dir = paths.home

    console.print(f"[bold]Backing up data from {source_dir} to {output_filename}...[/bold]")

    try:
        with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(source_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    # Archive path relative to source_dir
                    arcname = os.path.relpath(file_path, source_dir)
                    zipf.write(file_path, arcname)

        console.print(f"[green]Backup successful! Saved to {output_filename}[/green]")
    except Exception as e:
        console.print(f"[bold red]Backup failed:[/bold red] {e}")

def handle_restore_command(command_parts):
    """Restores user data from a zip file."""
    if len(command_parts) < 2:
        console.print("Usage: /restore [path_to_zip_file]")
        return

    zip_path = command_parts[1]

    # Handle home directory expansion and absolute paths
    zip_path = os.path.abspath(os.path.expanduser(zip_path))

    if not os.path.exists(zip_path):
        console.print(f"[bold red]Error:[/bold red] File not found: {zip_path}")
        return

    if not zipfile.is_zipfile(zip_path):
        console.print(f"[bold red]Error:[/bold red] Not a valid zip file: {zip_path}")
        return

    if not Confirm.ask(f"Are you sure you want to restore data from {zip_path}? This will overwrite current settings and memory."):
        console.print("[yellow]Restore cancelled.[/yellow]")
        return

    console.print("[bold]Restoring data...[/bold]")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            zipf.extractall(".")
        console.print("[green]Restore successful! Please restart the application to apply changes.[/green]")
    except Exception as e:
        console.print(f"[bold red]Restore failed:[/bold red] {e}")

def get_config_schema(agent=None):
    """
    Define the configuration schema with types, descriptions, and options.
    Returns a list of config item definitions.
    """
    schema = []

    # LLM Settings
    schema.append({
        "key": "LLM_MODEL",
        "type": "string",
        "default": "gpt-4o",
        "category": "LLM",
        "description": "Primary LLM model to use (e.g., gpt-4o, qwen3:8b, llama3.1)"
    })

    schema.append({
        "key": "LLM_PROVIDER",
        "type": "choice",
        "default": "openai",
        "options": ["openai", "ollama", "llama", "deepseek"],
        "category": "LLM",
        "description": "LLM provider"
    })

    # UI Settings
    schema.append({
        "key": "VERBOSE_THINKING",
        "type": "boolean",
        "default": True,
        "category": "UI",
        "description": "Show detailed thinking process"
    })

    schema.append({
        "key": "ENABLE_MARKDOWN",
        "type": "boolean",
        "default": True,
        "category": "UI",
        "description": "Enable markdown rendering"
    })

    # API Keys
    schema.append({
        "key": "OPENAI_API_KEY",
        "type": "secret",
        "default": "",
        "category": "API Keys",
        "description": "OpenAI API Key (required)"
    })

    schema.append({
        "key": "google_maps_api_key",
        "type": "secret",
        "default": "",
        "category": "API Keys",
        "description": "Google Maps API Key (for Map skill)"
    })

    # Add any additional configs from agent skills
    if agent:
        seen_keys = {item["key"] for item in schema}
        for skill in agent.skill_manager.skills:
            for req in skill.required_config:
                if req not in seen_keys:
                    schema.append({
                        "key": req,
                        "type": "string",
                        "default": "",
                        "category": "Skill: " + skill.name,
                        "description": f"Required for {skill.name}"
                    })
                    seen_keys.add(req)

    return schema


def interactive_config_ui(agent=None):
    """
    Interactive configuration UI with arrow key navigation and tabs.
    Use Tab/Shift+Tab to switch tabs, ↑/↓ to navigate, ←/→ to toggle, Enter to edit.
    """
    from prompt_toolkit import Application
    from prompt_toolkit.layout import Layout, HSplit, Window, WindowAlign
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.key_binding import KeyBindings

    config = load_config()
    schema = get_config_schema(agent)

    # Initialize config with defaults if missing
    for item in schema:
        if item["key"] not in config:
            config[item["key"]] = item["default"]

    # Store original config with defaults for comparison
    original_config = config.copy()

    # Tab state
    current_tab = 0  # 0 = Settings, 1 = Skills
    tabs = ["Settings", "Skills"]

    # Settings tab state
    settings_selected_index = 0

    # Skills tab state
    skills_selected_index = 0
    skills = []
    if agent:
        skills = agent.skill_manager.skills

    # Load skill enabled states from config
    skill_enabled = {}
    for skill in skills:
        config_key = f"SKILL_{skill.name.upper().replace(' ', '_')}_ENABLED"
        if config_key in config:
            skill.enabled = config[config_key]
        skill_enabled[skill.name] = skill.enabled

    def get_display_value(item):
        """Get formatted value for display."""
        value = config.get(item["key"], item["default"])
        if item["type"] == "boolean":
            return "ON" if value else "OFF"
        elif item["type"] == "secret" and value:
            return "*" * 8
        elif item["type"] == "choice":
            return str(value)
        else:
            return str(value) if value else "(not set)"

    def get_tabs_text():
        """Build the tab bar text."""
        result = []
        for i, tab_name in enumerate(tabs):
            if i == current_tab:
                result.append(("bold reverse", f" {tab_name} "))
            else:
                result.append(("", f" {tab_name} "))
            if i < len(tabs) - 1:
                result.append(("", "  "))
        return to_formatted_text(result)

    def get_settings_text():
        """Build the formatted text for the settings tab."""
        result = []
        result.append(("bold", "Collig Configuration Manager\n\n"))

        # Group by category
        categories = {}
        for item in schema:
            cat = item["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(item)

        # Build the list with categories
        current_index = 0
        for cat, items in categories.items():
            result.append(("bold cyan", f"  {cat}\n"))
            for item in items:
                prefix = "> " if current_index == settings_selected_index else "  "
                value = get_display_value(item)

                if current_index == settings_selected_index:
                    result.append(("bold cyan", f"{prefix}{item['key']}: "))
                    result.append(("bold reverse", f" {value} "))
                    result.append(("", f"  {item['description']}\n"))
                else:
                    result.append(("", f"{prefix}{item['key']}: {value}  {item['description']}\n"))
                current_index += 1

        return to_formatted_text(result)

    def get_skills_text():
        """Build the formatted text for the skills tab."""
        result = []
        result.append(("bold", "Skill Management\n\n"))

        if not skills:
            result.append(("dim", "  No skills available.\n"))
        else:
            for i, skill in enumerate(skills):
                prefix = "> " if i == skills_selected_index else "  "
                enabled = skill_enabled.get(skill.name, True)
                status = "[X]" if enabled else "[ ]"

                if i == skills_selected_index:
                    result.append(("bold cyan", f"{prefix}"))
                    result.append(("bold reverse", f" {status} "))
                    result.append(("", f" {skill.name}\n"))
                    result.append(("dim", f"      {skill.description}\n"))
                else:
                    result.append(("", f"{prefix}{status} {skill.name}\n"))

        return to_formatted_text(result)

    def get_footer_text():
        """Get the footer help text."""
        if current_tab == 0:
            return to_formatted_text([("dim", "[Tab] Switch Tabs  [↑/↓] Navigate  [←/→] Toggle  [Enter] Edit  [s] Save  [q] Quit")])
        else:
            return to_formatted_text([("dim", "[Tab] Switch Tabs  [↑/↓] Navigate  [←/→] Toggle  [s] Save  [q] Quit")])

    def get_content_text():
        """Get the main content text based on current tab."""
        if current_tab == 0:
            return get_settings_text()
        else:
            return get_skills_text()

    def save_config_and_update():
        """Save config and update environment variables."""
        # Save skill enabled states
        for skill in skills:
            config_key = f"SKILL_{skill.name.upper().replace(' ', '_')}_ENABLED"
            config[config_key] = skill_enabled.get(skill.name, True)
            skill.enabled = skill_enabled.get(skill.name, True)

        save_config(config)

        # Update environment variables for API keys
        for item in schema:
            if item["type"] == "secret" and item["key"] in config:
                os.environ[item["key"]] = config[item["key"]]
                if item["key"].endswith("_API_KEY"):
                    env_file = ".env"
                    if os.path.exists(env_file):
                        set_key(env_file, item["key"], config[item["key"]])

        # Update agent with new provider/model if changed
        if agent is not None:
            new_provider = config.get("LLM_PROVIDER")
            new_model = config.get("LLM_MODEL")
            if new_provider and (new_provider != original_config.get("LLM_PROVIDER") or new_model != original_config.get("LLM_MODEL")):
                agent.set_provider(new_provider, new_model)

            # Reinitialize agent with updated enabled skills
            agent._init_langchain_agent()

        return True

    def has_changes():
        """Check if there are unsaved changes."""
        current_config = load_config()

        # Check settings changes
        for key in config:
            if current_config.get(key) != config.get(key):
                return True

        # Check skill changes
        for skill in skills:
            config_key = f"SKILL_{skill.name.upper().replace(' ', '_')}_ENABLED"
            if current_config.get(config_key, True) != skill_enabled.get(skill.name, True):
                return True

        return False

    kb = KeyBindings()

    @kb.add("tab")
    def next_tab(event):
        nonlocal current_tab
        current_tab = (current_tab + 1) % len(tabs)
        tabs_control.text = get_tabs_text()
        content_control.text = get_content_text()
        footer_control.text = get_footer_text()

    @kb.add("s-tab")
    def prev_tab(event):
        nonlocal current_tab
        current_tab = (current_tab - 1) % len(tabs)
        tabs_control.text = get_tabs_text()
        content_control.text = get_content_text()
        footer_control.text = get_footer_text()

    @kb.add("up")
    def move_up(event):
        nonlocal settings_selected_index, skills_selected_index
        if current_tab == 0:
            settings_selected_index = (settings_selected_index - 1) % len(schema)
        else:
            if skills:
                skills_selected_index = (skills_selected_index - 1) % len(skills)
        content_control.text = get_content_text()

    @kb.add("down")
    def move_down(event):
        nonlocal settings_selected_index, skills_selected_index
        if current_tab == 0:
            settings_selected_index = (settings_selected_index + 1) % len(schema)
        else:
            if skills:
                skills_selected_index = (skills_selected_index + 1) % len(skills)
        content_control.text = get_content_text()

    @kb.add("left")
    def toggle_left(event):
        """Toggle boolean or cycle choice left."""
        if current_tab == 0:
            item = schema[settings_selected_index]
            if item["type"] == "boolean":
                config[item["key"]] = not config.get(item["key"], item["default"])
            elif item["type"] == "choice":
                current = config.get(item["key"], item["default"])
                options = item["options"]
                try:
                    idx = options.index(current)
                    new_idx = (idx - 1) % len(options)
                    config[item["key"]] = options[new_idx]
                except ValueError:
                    config[item["key"]] = options[0]
        else:
            if skills:
                skill = skills[skills_selected_index]
                skill_enabled[skill.name] = not skill_enabled.get(skill.name, True)
        content_control.text = get_content_text()

    @kb.add("right")
    def toggle_right(event):
        """Toggle boolean or cycle choice right."""
        if current_tab == 0:
            item = schema[settings_selected_index]
            if item["type"] == "boolean":
                config[item["key"]] = not config.get(item["key"], item["default"])
            elif item["type"] == "choice":
                current = config.get(item["key"], item["default"])
                options = item["options"]
                try:
                    idx = options.index(current)
                    new_idx = (idx + 1) % len(options)
                    config[item["key"]] = options[new_idx]
                except ValueError:
                    config[item["key"]] = options[0]
        else:
            if skills:
                skill = skills[skills_selected_index]
                skill_enabled[skill.name] = not skill_enabled.get(skill.name, True)
        content_control.text = get_content_text()

    @kb.add("enter")
    def edit_value(event):
        """Edit string or secret value (only in settings tab)."""
        if current_tab == 0:
            item = schema[settings_selected_index]
            if item["type"] in ["string", "secret"]:
                # Exit the main app to show input dialog
                event.app.exit(result=("edit", item))

    @kb.add("s")
    def save(event):
        """Save configuration."""
        save_config_and_update()
        event.app.exit(result=("saved",))

    @kb.add("q")
    @kb.add("escape")
    @kb.add("c-c")
    def quit(event):
        """Quit without saving (prompt if changes)."""
        if has_changes():
            event.app.exit(result=("confirm_quit",))
        else:
            event.app.exit(result=("quit",))

    # Create UI components
    tabs_control = FormattedTextControl(text=get_tabs_text())
    tabs_window = Window(content=tabs_control, height=1, align=WindowAlign.CENTER)

    content_control = FormattedTextControl(text=get_content_text())
    content_window = Window(
        content=content_control,
        width=Dimension(min=60, preferred=80),
        height=Dimension(min=15, preferred=22),
        align=WindowAlign.LEFT
    )

    footer_control = FormattedTextControl(text=get_footer_text())
    footer_window = Window(content=footer_control, height=1)

    layout = Layout(HSplit([tabs_window, content_window, footer_window]))
    app = Application(layout=layout, key_bindings=kb, full_screen=False)

    while True:
        result = app.run()

        if not result:
            break

        if result[0] == "edit":
            item = result[1]
            current_value = config.get(item["key"], item["default"])
            is_password = item["type"] == "secret"
            try:
                new_value = prompt(
                    message=f"Enter {item['key']}: ",
                    default=str(current_value),
                    is_password=is_password
                )
                if new_value is not None:
                    config[item["key"]] = new_value
                content_control.text = get_content_text()
            except:
                pass

        elif result[0] == "saved":
            console.print("[green]Configuration saved successfully![/green]")
            break

        elif result[0] == "confirm_quit":
            if Confirm.ask("You have unsaved changes. Save before quitting?"):
                save_config_and_update()
                console.print("[green]Configuration saved![/green]")
            break

        elif result[0] == "quit":
            break


def handle_config_command(command_parts, agent=None):
    """
    Handles configuration commands:
    - config (interactive UI)
    - config list
    - config set [key] [value]
    """
    if len(command_parts) < 2:
        # Launch interactive UI
        try:
            interactive_config_ui(agent)
            return
        except Exception as e:
            console.print(f"[dim]Interactive config failed: {e}, falling back to basic mode.[/dim]")
            # Fall through to basic help

    if len(command_parts) < 2:
        console.print("[bold]Configuration Manager[/bold]")
        console.print("Usage:")
        console.print("  config                    - Interactive configuration UI")
        console.print("  config list               - Show current configuration")
        console.print("  config set [key] [value]  - Set a configuration value")

        if agent:
            console.print("\n[bold]Available Configuration Options:[/bold]")
            for skill in agent.skill_manager.skills:
                if skill.required_config:
                    reqs = ", ".join(skill.required_config)
                    console.print(f"  [cyan]{skill.name}[/cyan]: {reqs}")
        return

    action = command_parts[1]
    config = load_config()

    if action == "list":
        console.print(Panel(json.dumps(config, indent=2), title="Current Configuration"))

        if agent:
            console.print("\n[bold]Missing Required Configuration:[/bold]")
            missing_found = False
            for skill in agent.skill_manager.skills:
                for req in skill.required_config:
                    if req not in config:
                        console.print(f"  [red]MISSING[/red] {req} (for {skill.name})")
                        missing_found = True
            if not missing_found:
                console.print("  [green]All required configurations are set![/green]")

    elif action == "set":
        if len(command_parts) < 4:
            console.print("Usage: config set [key] [value]")
            return
        key = command_parts[2]
        value = " ".join(command_parts[3:]) # Allow spaces in value
        config[key] = value
        save_config(config)
        console.print(f"[green]Configuration updated:[/green] {key} = {value}")

        # If setting an API key, also update .env and os.environ
        if key.endswith("_API_KEY"):
            env_file = ".env"
            if not os.path.exists(env_file):
                with open(env_file, "w") as f:
                    f.write("")
            set_key(env_file, key, value)
            os.environ[key] = value
            console.print(f"[green]Environment variable {key} updated.[/green]")

        # If setting provider or model, update the agent immediately
        if agent is not None and (key == "LLM_PROVIDER" or key == "LLM_MODEL"):
            provider = config.get("LLM_PROVIDER", agent.llm_provider)
            model = config.get("LLM_MODEL", agent.llm_model)
            if key == "LLM_PROVIDER":
                provider = value
            else:
                model = value
            agent.set_provider(provider, model)
            console.print(f"[green]Agent updated to use {provider} ({model})[/green]")

        # Reload agent with new config?
        # Ideally, we should restart or trigger a reload, but for now user might need to restart.
        console.print("[dim]Note: You may need to restart the session for changes to take effect in some skills.[/dim]")
    else:
        console.print(f"Unknown config action: {action}")

def check_setup():
    """Checks if the environment is set up (e.g., API keys exist)."""
    # 1. Check environment variable
    if os.getenv("OPENAI_API_KEY"):
        return True

    # 2. Check config file
    config = load_config()
    if config.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = config["OPENAI_API_KEY"]
        return True

    return False

def run_setup_wizard():
    """Runs the first-time setup wizard."""
    console.print(Panel.fit("[bold green]Welcome to Collig Co-worker AI![/bold green]\n\nIt looks like this is your first time running Collig.\nLet's get you set up.", title="Setup Wizard"))

    if Confirm.ask("Do you want to configure your OpenAI API Key now?"):
        api_key = RichPrompt.ask("Enter your OpenAI API Key", password=True)

        env_file = ".env"
        if not os.path.exists(env_file):
            with open(env_file, "w") as f:
                f.write("")

        set_key(env_file, "OPENAI_API_KEY", api_key)
        os.environ["OPENAI_API_KEY"] = api_key # Update current session
        console.print("[green]API Key saved successfully![/green]")
    else:
        console.print("[yellow]Skipping API setup. Some features may not work.[/yellow]")

    console.print("\n[bold]Setup Complete![/bold]\n")

def print_banner():
    """Prints a cool ASCII art banner with a robot and typing animation."""
    import zlib
    import base64

    _L = 'eJxTUHg0rQMdTZ2uwAUTnzrl0dQJSGguktREBTDAJjB1Fi5zwXIoRoJNrampweUULC6BSXIh2wxn4xLF7iigsXO5CLsK6BKcviVWAGs4Y7F4kNmNbCiRbKjBpMYrNIUh+QFZC/XiFQDYYadb'

    def _d(s):
        return zlib.decompress(base64.b64decode(s)).decode('utf-8')

    letters = [block.split("\n") for block in _d(_L).split("|||")]

    console.print() # Spacer

    # Animate Wall-E driving from Right to Left
    terminal_width = console.width
    # Canvas to hold fixed/arrived letters
    fixed_lines = [""] * 6

    with Live(console=console, refresh_per_second=60, transient=False) as live:
        for letter_lines in letters:
            w = len(letter_lines[0])
            for pad in range(terminal_width - len(fixed_lines[0]), 0, -5):
                live.update(Text('\n'.join(fixed_lines[i] + ' ' * pad + letter_lines[i]
                                         for i in range(6)), style="bold #C56F52"))
                time.sleep(0.005)
            for i in range(6):
                fixed_lines[i] += letter_lines[i]

        # Final update to ensure everything is clean
        final_text = Text()
        for line in fixed_lines:
            final_text.append(line + "\n", style="bold #C56F52")
        live.update(final_text)

    # Typing animation for the tagline
    tagline = "Your AI Assistant for Life & Work"

    # Use console.print char-by-char with style to avoid markup nesting errors
    for char in tagline:
        console.print(char, style="italic dim", end="")
        time.sleep(0.05)
    console.print() # Newline after animation

def main():
    parser = argparse.ArgumentParser(description="Collig CLI")
    parser.add_argument("--session", type=str, help="Session ID to resume")
    args = parser.parse_args()

    print_banner()

    if not check_setup():
        run_setup_wizard()

    # Import agent AFTER setup to ensure env vars are loaded if agent relies on them at import time
    try:
        import time as time_module
        start_time = time_module.time()
        console.print("[dim]Importing skills...[/dim]")
        from agent import agent
        from skills.menu import set_menu_functions
        from skills.news import NewsSkill
        import_time = time_module.time() - start_time
        console.print(f"[dim]Agent imported in {import_time:.2f}s[/dim]")

        # Set the menu functions for the MenuSkill
        set_menu_functions(interactive_select, interactive_menu)

        # Set the news functions for the NewsSkill
        set_news_functions(NewsSkill.get_news_cache, NewsSkill.get_last_query)

        # Newline after the overwriting registration logs
        print()

        # Load and apply configuration to skills
        config_start = time_module.time()
        console.print("[dim]Loading configuration...[/dim]")
        config = load_config()
        config_time = time_module.time() - config_start
        console.print(f"[dim]Configuration loaded in {config_time:.2f}s[/dim]")

        # Initialize markdown preference
        ENABLE_MARKDOWN = config.get("ENABLE_MARKDOWN", True)

        skills_start = time_module.time()
        console.print("[dim]Configuring skills...[/dim]")
        agent.skill_manager.configure(config)
        for skill in agent.skill_manager.skills:
            skill.configure(config)
        skills_time = time_module.time() - skills_start
        console.print(f"[dim]Skills configured in {skills_time:.2f}s[/dim]")

    except Exception as e:
        console.print(f"[bold red]Failed to initialize agent:[/bold red] {e}")
        return

    # Initialize prompt_toolkit session
    completer = SkillCommandCompleter(agent)
    pt_session = PromptSession(
        history=InMemoryHistory(),
        completer=completer,
        complete_while_typing=True
    )

    # Custom style for prompt_toolkit
    style = Style.from_dict({
        'prompt': 'bold ansigreen',
        'completion-menu.completion': 'bg:#008888 #ffffff',
        'completion-menu.completion.current': 'bg:#00aaaa #000000',
        'scrollbar.background': 'bg:#88aaaa',
        'scrollbar.button': 'bg:#222222',
    })

    session_id = args.session
    if session_id:
        console.print(f"[bold cyan]Resuming session: {session_id}[/bold cyan]")
        history = agent.session_manager.get_history(session_id)
        if history:
            console.print(Panel("Restoring history...", style="dim"))
            for msg in history:
                role = msg["role"]
                content = msg["content"]
                color = "green" if role == "user" else "blue"
                label = "You" if role == "user" else "Collig"
                console.print(f"[bold {color}]{label}:[/bold {color}] {content}")
            console.print()
    else:
        session_id = agent.session_manager.create_session()
        console.print(f"[bold cyan]New session started: {session_id}[/bold cyan]")

    console.print("[bold blue]Collig Co-worker AI - CLI Mode[/bold blue]")
    console.print("Type [bold yellow]/[/bold yellow] to see available commands.")
    console.print("Type [bold yellow]'exit'[/bold yellow] or [bold yellow]'quit'[/bold yellow] to end the session.")
    console.print("Press [bold yellow]Esc[/bold yellow] or [bold yellow]Ctrl+C[/bold yellow] to cancel current operation.")
    console.print("Use [bold yellow]/toggle markdown[/bold yellow] to enable/disable markdown formatting.\n")

    while True:
        try:
            # Use prompt_toolkit's session.prompt() for history navigation
            user_input = pt_session.prompt([('class:prompt', 'You: ')], style=style)

            # Handle built-in CLI commands (like config)
            if user_input.startswith("/"):
                # Remove slash if it's there
                user_input = user_input[1:]

            if user_input.lower() in ["exit", "quit"]:
                console.print(Panel(
                    f"Session ID: [bold cyan]{session_id}[/bold cyan]\n\n"
                    f"To resume this session later, run:\n"
                    f"[green]make pa session={session_id}[/green]",
                    title="Goodbye!",
                    border_style="green"
                ))
                break

            if not user_input.strip():
                continue

            if user_input.lower() == "clear":
                console.clear()
                continue

            if user_input.startswith("run"):
                # Handle shell execution
                cmd_parts = user_input.split(" ", 1)
                if len(cmd_parts) < 2:
                    console.print("Usage: /run [command] [args...]")
                else:
                    cmd_to_run = cmd_parts[1]
                    import subprocess
                    try:
                        console.print(f"[dim]Running: {cmd_to_run}[/dim]")
                        # Run command and stream output
                        process = subprocess.Popen(
                            cmd_to_run,
                            shell=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True
                        )
                        stdout, stderr = process.communicate()

                        if stdout:
                            console.print(stdout.rstrip())
                        if stderr:
                            console.print(f"[red]{stderr.rstrip()}[/red]")

                    except Exception as e:
                        console.print(f"[bold red]Error running command:[/bold red] {e}")
                continue

            if user_input.lower() == "restart":
                # Restart the application with the same session ID
                console.print(Panel(
                    f"[bold cyan]Restarting session {session_id}...[/bold cyan]",
                    title="Restarting",
                    border_style="yellow"
                ))
                # Use os.execv to replace the current process
                # We need to reconstruct the command line arguments
                # The original command was likely "make pa session=..." or "python backend/cli.py ..."
                # We want to run: python backend/cli.py --session <session_id>

                # Get the python interpreter
                python = sys.executable

                # Get the script path
                script = os.path.abspath(__file__)

                # New arguments
                args_list = [python, script, "--session", session_id]

                # Execute
                os.execv(python, args_list)

            if user_input.startswith("backup"):
                handle_backup_command()
                continue

            if user_input.startswith("restore"):
                handle_restore_command(user_input.split())
                continue

            if user_input.startswith("news"):
                try:
                    from skills.news import NewsSkill
                    news_cache = NewsSkill.get_news_cache()
                    if news_cache:
                        news_query = NewsSkill.get_last_query()
                        news_action = interactive_news_menu(news_cache, news_query)
                        if news_action:
                            handle_news_action(news_action, agent)
                    else:
                        console.print("[yellow]No news items available. Try searching for news first![/yellow]")
                except Exception as e:
                    console.print(f"[red]Error opening news menu: {e}[/red]")
                continue

            if user_input.startswith("provider"):
                parts = user_input.split()
                if len(parts) < 2:
                    console.print(f"[bold]Current Provider:[/bold] {agent.llm_provider} (Model: {agent.llm_model})")
                    console.print("Usage: /provider [list|openai|llama|deepseek] [model_name (optional)]")
                elif parts[1].lower() == "list":
                    console.print("[bold]Available Providers & Models:[/bold]")
                    console.print(agent.get_available_models())
                    console.print(f"\n[bold]Current:[/bold] {agent.llm_provider} (Model: {agent.llm_model})")
                else:
                    provider = parts[1]
                    model = parts[2] if len(parts) > 2 else None
                    msg = agent.set_provider(provider, model)
                    console.print(f"[green]{msg}[/green]")

                    # Persist to config
                    config = load_config()
                    config["LLM_PROVIDER"] = agent.llm_provider
                    config["LLM_MODEL"] = agent.llm_model
                    save_config(config)
                    console.print("[dim]Preference saved to config.json[/dim]")
                continue

            if user_input.lower() == "quiet" or user_input.lower().startswith("quiet "):
                msg = agent.set_verbose(False)
                console.print(f"[green]{msg}[/green]")
                continue

            if user_input.lower() == "verbose" or user_input.lower().startswith("verbose "):
                msg = agent.set_verbose(True)
                console.print(f"[green]{msg}[/green]")
                continue

            if user_input.lower().startswith("toggle thinking"):
                msg = agent.toggle_verbose()
                console.print(f"[green]{msg}[/green]")
                continue

            if user_input.lower().startswith("toggle markdown"):
                ENABLE_MARKDOWN = not ENABLE_MARKDOWN
                status = "enabled" if ENABLE_MARKDOWN else "disabled"

                # Save to config
                config = load_config()
                config["ENABLE_MARKDOWN"] = ENABLE_MARKDOWN
                save_config(config)

                console.print(f"[green]Markdown rendering {status}.[/green]")
                continue

            if user_input.lower().startswith("stats"):
                # Parse command: /stats [session|overall]
                parts = user_input.lower().split()
                mode = "both"  # default: show both
                if len(parts) > 1:
                    if parts[1] in ["session", "sess"]:
                        mode = "session"
                    elif parts[1] in ["overall", "all", "total"]:
                        mode = "overall"

                from datetime import datetime

                # Function to render a stats bar
                def render_bar(prompt_tokens, completion_tokens, total_tokens, width=40):
                    if total_tokens <= 0:
                        return " " * width
                    prompt_pct = prompt_tokens / total_tokens
                    completion_pct = completion_tokens / total_tokens
                    prompt_chars = int(width * prompt_pct)
                    completion_chars = int(width * completion_pct)
                    # Ensure at least something shows if we have tokens
                    if prompt_chars == 0 and prompt_tokens > 0:
                        prompt_chars = 1
                    if completion_chars == 0 and completion_tokens > 0:
                        completion_chars = 1
                    # Adjust to fit
                    while prompt_chars + completion_chars > width:
                        if completion_chars > 1:
                            completion_chars -= 1
                        elif prompt_chars > 1:
                            prompt_chars -= 1
                    return (
                        "[cyan]" + "█" * prompt_chars + "[/cyan]" +
                        "[green]" + "█" * completion_chars + "[/green]" +
                        " " * (width - prompt_chars - completion_chars)
                    ), prompt_pct, completion_pct

                sections = []

                # Session Stats Section
                if mode in ["both", "session"]:
                    session_stats = agent.get_token_stats(session_id)
                    if session_stats:
                        try:
                            first_ts = datetime.fromisoformat(session_stats["first_interaction"])
                            last_ts = datetime.fromisoformat(session_stats["last_interaction"])
                            first_str = first_ts.strftime("%b %d, %H:%M")
                            last_str = last_ts.strftime("%b %d, %H:%M")
                            # Calculate session duration
                            duration = last_ts - first_ts
                            hours, remainder = divmod(duration.total_seconds(), 3600)
                            minutes, _ = divmod(remainder, 60)
                            if hours > 24:
                                days = int(hours // 24)
                                hours = int(hours % 24)
                                duration_str = f"{days}d {hours}h {int(minutes)}m"
                            else:
                                duration_str = f"{int(hours)}h {int(minutes)}m"
                        except:
                            first_str = session_stats["first_interaction"]
                            last_str = session_stats["last_interaction"]
                            duration_str = "unknown"

                        total_tokens = session_stats['total_tokens']
                        prompt_tokens = session_stats['total_prompt_tokens']
                        completion_tokens = session_stats['total_completion_tokens']
                        bar, prompt_pct, completion_pct = render_bar(prompt_tokens, completion_tokens, total_tokens)

                        session_section = f"""  [bold cyan]Session Stats[/bold cyan]  [dim]────────────────────────────────────────────────[/dim]

  [bold]Session[/bold]:      {session_stats['session_id'][:8]}...
  [bold]Interactions[/bold]: {session_stats['interaction_count']}
  [bold]Duration[/bold]:     {duration_str}
  [bold]First[/bold]:        {first_str}
  [bold]Last[/bold]:         {last_str}

  {bar}
  [cyan]◯ Request[/cyan]  {prompt_tokens:>12,}  [dim]{prompt_pct*100:.0f}%[/dim]
  [green]◯ Response[/green] {completion_tokens:>12,}  [dim]{completion_pct*100:.0f}%[/dim]
  [bold white]● Total[/bold white]    {total_tokens:>12,}

  [cyan]Request[/cyan]:   {session_stats['avg_prompt_tokens']:>8,} tokens  [dim]avg per interaction[/dim]
  [green]Response[/green]:  {session_stats['avg_completion_tokens']:>8,} tokens  [dim]avg per interaction[/dim]
  [bold white]Total[/bold white]:     {session_stats['avg_total_tokens']:>8,} tokens  [dim]avg per interaction[/dim]
"""
                        sections.append(session_section)

                # Overall Stats Section
                if mode in ["both", "overall"]:
                    overall_stats = agent.get_overall_token_stats()
                    if overall_stats:
                        try:
                            first_ts = datetime.fromisoformat(overall_stats["first_interaction"])
                            last_ts = datetime.fromisoformat(overall_stats["last_interaction"])
                            first_str = first_ts.strftime("%b %d, %Y")
                            last_str = last_ts.strftime("%b %d, %Y")
                            # Calculate overall duration
                            duration = last_ts - first_ts
                            duration_str = f"{duration.days} days"
                        except:
                            first_str = overall_stats["first_interaction"]
                            last_str = overall_stats["last_interaction"]
                            duration_str = "unknown"

                        total_tokens = overall_stats['total_tokens']
                        prompt_tokens = overall_stats['total_prompt_tokens']
                        completion_tokens = overall_stats['total_completion_tokens']
                        bar, prompt_pct, completion_pct = render_bar(prompt_tokens, completion_tokens, total_tokens)

                        overall_section = f"""  [bold yellow]Overall Stats[/bold yellow]  [dim]─────────────────────────────────────────────[/dim]

  [bold]Sessions[/bold]:     {overall_stats['total_sessions']}
  [bold]Interactions[/bold]: {overall_stats['total_interactions']}
  [bold]Period[/bold]:       {first_str} - {last_str}
  [bold]Duration[/bold]:     {duration_str}

  {bar}
  [cyan]◯ Request[/cyan]  {prompt_tokens:>12,}  [dim]{prompt_pct*100:.0f}%[/dim]
  [green]◯ Response[/green] {completion_tokens:>12,}  [dim]{completion_pct*100:.0f}%[/dim]
  [bold white]● Total[/bold white]    {total_tokens:>12,}

  [bold white]Per Session (avg):[/bold white]
  [cyan]Request[/cyan]:   {overall_stats['avg_prompt_per_session']:>8,} tokens
  [green]Response[/green]:  {overall_stats['avg_completion_per_session']:>8,} tokens
  [bold white]Total[/bold white]:     {overall_stats['avg_total_per_session']:>8,} tokens

  [bold white]Per Interaction (avg):[/bold white]
  [cyan]Request[/cyan]:   {overall_stats['avg_prompt_per_interaction']:>8,} tokens
  [green]Response[/green]:  {overall_stats['avg_completion_per_interaction']:>8,} tokens
  [bold white]Total[/bold white]:     {overall_stats['avg_total_per_interaction']:>8,} tokens
"""
                        sections.append(overall_section)

                if not sections:
                    console.print(Panel("No token usage data yet. Start a conversation!", title="Token Statistics", border_style="dim"))
                else:
                    # Join sections with a divider
                    divider = "\n  [dim]────────────────────────────────────────────────────────────[/dim]\n"
                    full_content = divider.join(sections)
                    header = "  [bold white]Token Statistics[/bold white]  [dim]────────────────────────────────────────────[/dim]\n"
                    footer = "\n  [dim]Use /stats session or /stats overall to see only one section[/dim]"
                    console.print(Panel(header + full_content + footer, border_style="cyan", padding=(0, 2)))
                continue

            if user_input.startswith("status"):
                console.print(Panel(f"[bold]System Status[/bold]\nChecking connection to {agent.llm_provider}...", title="Status Check"))

                # Check 1: Provider Config
                console.print(f"• Provider: [cyan]{agent.llm_provider}[/cyan]")
                console.print(f"• Model: [cyan]{agent.llm_model}[/cyan]")
                console.print(f"• Markdown: {'[green]enabled[/green]' if ENABLE_MARKDOWN else '[yellow]disabled[/yellow]'}")

                # Check 2: API Key / Connection
                status = "[green]OK[/green]"
                error_msg = ""
                api_key_source = ""
                api_key_preview = ""

                def get_api_key_info(env_var_name):
                    env_key = os.getenv(env_var_name)
                    config_key = load_config().get(env_var_name)

                    if config_key:
                        source = "config.json"
                        key = config_key
                    elif env_key:
                        source = "environment variable"
                        key = env_key
                    else:
                        source = None
                        key = None

                    return key, source

                if agent.llm_provider == "openai":
                    api_key, source = get_api_key_info("OPENAI_API_KEY")
                    if not api_key:
                        status = "[red]MISSING API KEY[/red]"
                        error_msg = "Please set OPENAI_API_KEY in config.json or .env via '/config set'"
                    else:
                        api_key_source = source
                        api_key_preview = api_key[:10] + "..." + api_key[-4:] if len(api_key) > 14 else "***"
                elif agent.llm_provider == "deepseek":
                    api_key, source = get_api_key_info("DEEPSEEK_API_KEY")
                    if not api_key:
                        status = "[red]MISSING API KEY[/red]"
                        error_msg = "Please set DEEPSEEK_API_KEY in config.json or .env via '/config set'"
                    else:
                        api_key_source = source
                        api_key_preview = api_key[:10] + "..." + api_key[-4:] if len(api_key) > 14 else "***"
                elif agent.llm_provider == "ollama" or agent.llm_provider == "llama":
                    # Check if ollama is running
                    import subprocess
                    try:
                        subprocess.run(["ollama", "--version"], capture_output=True, check=True)
                    except:
                        status = "[red]OLLAMA NOT FOUND[/red]"
                        error_msg = "Ensure Ollama is installed and running."

                console.print(f"• Configuration: {status}")
                if error_msg:
                    console.print(f"  ➜ {error_msg}")
                if api_key_source:
                    console.print(f"  ➜ API Key Source: [cyan]{api_key_source}[/cyan]")
                    console.print(f"  ➟ API Key: [dim]{api_key_preview}[/dim]")

                # Check 3: Live LLM Request
                if "OK" in status:
                    console.print("• LLM Connection: [yellow]Testing...[/yellow]", end="\r")
                    try:
                        if hasattr(agent, "agent_executor"):
                            test_msg = "what is 2+2"
                            result = agent.process_message(test_msg, include_history=False, verbose=False)
                            resp = result.get("response", "").strip()
                            if resp:
                                console.print("• LLM Connection: [green]OK[/green] (Response received)")
                            else:
                                console.print(f"• LLM Connection: [yellow]WARNING[/yellow] (Empty response)")
                        else:
                             console.print("• LLM Connection: [red]FAILED[/red] (Agent not initialized)")
                    except Exception as e:
                        console.print(f"• LLM Connection: [red]FAILED[/red] ({e})")

                continue

            if user_input.startswith("doctor") or user_input.startswith("test"):
                console.print(Panel(f"[bold]System Doctor[/bold]\nChecking connection to {agent.llm_provider}...", title="Health Check"))

                # Check 1: Provider Config
                console.print(f"• Provider: [cyan]{agent.llm_provider}[/cyan]")
                console.print(f"• Model: [cyan]{agent.llm_model}[/cyan]")

                # Check 2: API Key / Connection
                status = "[green]OK[/green]"
                error_msg = ""

                if agent.llm_provider == "openai":
                    if not os.getenv("OPENAI_API_KEY"):
                        status = "[red]MISSING API KEY[/red]"
                        error_msg = "Please set OPENAI_API_KEY in .env or via '/config set'"
                elif agent.llm_provider == "deepseek":
                    if not os.getenv("DEEPSEEK_API_KEY"):
                        status = "[red]MISSING API KEY[/red]"
                        error_msg = "Please set DEEPSEEK_API_KEY in .env or via '/config set'"
                elif agent.llm_provider == "ollama" or agent.llm_provider == "llama":
                    # Check if ollama is running
                    import subprocess
                    try:
                        subprocess.run(["ollama", "--version"], capture_output=True, check=True)
                    except:
                        status = "[red]OLLAMA NOT FOUND[/red]"
                        error_msg = "Ensure Ollama is installed and running."

                console.print(f"• Configuration: {status}")
                if error_msg:
                    console.print(f"  ➜ {error_msg}")

                # Check 3: Live LLM Request
                if "OK" in status:
                    console.print("• LLM Connection: [yellow]Testing...[/yellow]", end="\r")
                    try:
                        # Create a simple direct invocation bypassing the agent loop for speed
                        if hasattr(agent, "agent_executor"):
                            # Using invoke directly on the LLM object inside the agent would be cleaner
                            # but agent.agent_executor is a compiled graph.
                            # Let's just ask a simple hello via process_message but silent
                            test_msg = "what is 2+2"

                            # We can use the agent's LLM directly if we can access it,
                            # but agent doesn't expose 'llm' publicly in the class def above.
                            # So we go through process_message.
                            # print("Send test message:", test_msg)
                            result = agent.process_message(test_msg, include_history=False, verbose=False)
                            # print(">>>result", result)
                            resp = result.get("response", "").strip()
                            # Check for any non-empty response
                            if resp:
                                console.print("• LLM Connection: [green]OK[/green] (Response received)")
                            else:
                                console.print(f"• LLM Connection: [yellow]WARNING[/yellow] (Empty response)")
                        else:
                             console.print("• LLM Connection: [red]FAILED[/red] (Agent not initialized)")
                    except Exception as e:
                        console.print(f"• LLM Connection: [red]FAILED[/red] ({e})")

                continue

            if user_input.startswith("config"):
                handle_config_command(user_input.split(), agent)
                # Update runtime config for skills immediately
                new_config = load_config()
                for skill in agent.skill_manager.skills:
                    skill.configure(new_config)
                continue

            # Inner try-except for agent processing - can be interrupted with Ctrl+C
            result = None
            try:
                with console.status("[bold yellow]Thinking...[/bold yellow]"):
                    result = agent.process_message(user_input, session_id=session_id)
            except KeyboardInterrupt:
                console.print("\n[yellow]Operation cancelled. Returning to prompt...[/yellow]\n")
                continue

            if result:
                response = result["response"]
                action = result["action"]
                data = result.get("data", {})

                # Check if response contains markdown formatting
                markdown_patterns = ["**", "#", "[", "- ", "1.", "```", "___"]
                if ENABLE_MARKDOWN and any(pattern in response for pattern in markdown_patterns):
                    # Render as markdown
                    console.print("[bold blue]Collig:[/bold blue]")
                    try:
                        console.print(Markdown(response))
                    except Exception:
                        # Fallback to plain text if markdown rendering fails
                        console.print(response)
                else:
                    # Render as plain text
                    console.print(f"[bold blue]Collig:[/bold blue] {response}")

                # Show token usage statistics
                prompt_tokens = result.get("prompt_tokens", 0)
                completion_tokens = result.get("completion_tokens", 0)
                total_tokens = result.get("total_tokens", 0)
                if prompt_tokens > 0 or completion_tokens > 0:
                    console.print(f"[dim](Request: {prompt_tokens}, Response: {completion_tokens}, Total: {total_tokens})[/dim]")

                if action:
                    console.print(f"[dim italic]Action triggered: {action}[/dim italic]")

                    # Handle specific actions
                    if action == "open_url":
                        url = data.get("url")
                        if url:
                            import webbrowser
                            try:
                                webbrowser.open(url)
                                console.print(f"[green]Creating browser tab for: {url}[/green]")
                            except Exception as e:
                                console.print(f"[red]Failed to open browser: {e}[/red]")

                # Check if news was just searched - offer interactive menu
                try:
                    from skills.news import NewsSkill
                    if NewsSkill.has_just_searched():
                        NewsSkill.clear_search_flag()
                        news_cache = NewsSkill.get_news_cache()
                        if news_cache:
                            console.print()
                            if Confirm.ask("[bold cyan]📰 Open interactive news browser?[/bold cyan]", default=True):
                                news_query = NewsSkill.get_last_query()
                                news_action = interactive_news_menu(news_cache, news_query)
                                if news_action:
                                    handle_news_action(news_action, agent)
                except Exception as e:
                    # If news menu fails, just continue quietly
                    pass

                console.print() # Empty line for spacing

        except KeyboardInterrupt:
            # Double Ctrl+C to exit
            console.print("\n[bold blue]Collig:[/bold blue] Goodbye!")
            break
        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {str(e)}")

if __name__ == "__main__":
    main()
