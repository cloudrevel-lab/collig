import os
import sys
import argparse
import json
import zipfile
import shutil
from datetime import datetime
from rich.console import Console
from rich.prompt import Prompt as RichPrompt, Confirm
from rich.markdown import Markdown
from rich.panel import Panel
from dotenv import load_dotenv, set_key

# Import prompt_toolkit for advanced input handling
from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

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
            ("config list", "Show current configuration"),
            ("config set", "Set a configuration value"),
            ("backup", "Backup user data to a zip file"),
            ("restore", "Restore user data from a zip file"),
            ("provider", "Switch LLM provider (openai/llama)"),
            ("run", "Run a shell command (e.g., /run ls -la)"),
            ("restart", "Restart the session (reload code)"),
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

console = Console()

CONFIG_FILE = "config.json"

def handle_backup_command():
    """Backs up user data to a zip file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"collig_backup_{timestamp}.zip"

    files_to_backup = ["config.json", ".env"]
    dirs_to_backup = ["sessions", "data"]

    console.print(f"[bold]Backing up data to {output_filename}...[/bold]")

    try:
        with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            count = 0
            for file in files_to_backup:
                if os.path.exists(file):
                    zipf.write(file)
                    count += 1

            for directory in dirs_to_backup:
                if os.path.exists(directory):
                    for root, dirs, files in os.walk(directory):
                        for file in files:
                            file_path = os.path.join(root, file)
                            zipf.write(file_path)
                            count += 1
        console.print(f"[green]Backup successful! {count} files saved to {output_filename}[/green]")
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

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

def handle_config_command(command_parts, agent=None):
    """
    Handles configuration commands:
    - config list
    - config set [key] [value]
    """
    if len(command_parts) < 2:
        console.print("[bold]Configuration Manager[/bold]")
        console.print("Usage:")
        console.print("  config list              - Show current configuration")
        console.print("  config set [key] [value] - Set a configuration value")

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

        # Reload agent with new config?
        # Ideally, we should restart or trigger a reload, but for now user might need to restart.
        console.print("[dim]Note: You may need to restart the session for changes to take effect in some skills.[/dim]")
    else:
        console.print(f"Unknown config action: {action}")

def check_setup():
    """Checks if the environment is set up (e.g., API keys exist)."""
    return os.getenv("OPENAI_API_KEY") is not None

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

def main():
    parser = argparse.ArgumentParser(description="Collig CLI")
    parser.add_argument("--session", type=str, help="Session ID to resume")
    args = parser.parse_args()

    if not check_setup():
        run_setup_wizard()

    # Import agent AFTER setup to ensure env vars are loaded if agent relies on them at import time
    try:
        from agent import agent

        # Load and apply configuration to skills
        config = load_config()
        for skill in agent.skill_manager.skills:
            skill.configure(config)

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
    console.print("Type 'exit' or 'quit' to end the session.\n")

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

            if user_input.startswith("config"):
                handle_config_command(user_input.split(), agent)
                # Update runtime config for skills immediately
                new_config = load_config()
                for skill in agent.skill_manager.skills:
                    skill.configure(new_config)
                continue

            with console.status("[bold yellow]Thinking...[/bold yellow]"):
                result = agent.process_message(user_input, session_id=session_id)

            response = result["response"]
            action = result["action"]
            data = result.get("data", {})

            console.print(f"[bold blue]Collig:[/bold blue] {response}")

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

            console.print() # Empty line for spacing

        except KeyboardInterrupt:
            console.print("\n[bold blue]Collig:[/bold blue] Goodbye!")
            break
        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {str(e)}")

if __name__ == "__main__":
    main()
