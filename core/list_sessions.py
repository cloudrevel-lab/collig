import os
import sys

# Add parent directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
from rich.console import Console
from rich.table import Table
from datetime import datetime
from core.paths import paths

# Define sessions directory
SESSIONS_DIR = paths.sessions_dir

console = Console()

def list_sessions():
    if not os.path.exists(SESSIONS_DIR):
        console.print(f"[yellow]No sessions directory found at {SESSIONS_DIR}[/yellow]")
        return

    sessions = []

    # Iterate through all json files in the sessions directory
    for filename in os.listdir(SESSIONS_DIR):
        if filename.endswith(".json"):
            file_path = os.path.join(SESSIONS_DIR, filename)
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)

                    # Extract info
                    session_id = data.get("id", filename.replace(".json", ""))
                    created_at_str = data.get("created_at", "Unknown")

                    # Try to parse date for sorting
                    try:
                        created_at_dt = datetime.fromisoformat(created_at_str)
                        created_at_display = created_at_dt.strftime("%Y-%m-%d %H:%M:%S")
                    except:
                        created_at_dt = datetime.min
                        created_at_display = created_at_str

                    msg_count = len(data.get("messages", []))

                    sessions.append({
                        "id": session_id,
                        "created_at_dt": created_at_dt,
                        "created_at_display": created_at_display,
                        "msg_count": msg_count
                    })
            except Exception as e:
                console.print(f"[red]Error reading {filename}: {e}[/red]")

    # Sort by creation time (newest first)
    sessions.sort(key=lambda x: x["created_at_dt"], reverse=True)

    if not sessions:
        console.print("[yellow]No sessions found.[/yellow]")
        return

    # Create table
    table = Table(title="Available Sessions")
    table.add_column("Session ID", style="cyan", no_wrap=True)
    table.add_column("Created At", style="green")
    table.add_column("Messages", justify="right")

    for session in sessions:
        table.add_row(
            session["id"],
            session["created_at_display"],
            str(session["msg_count"])
        )

    console.print(table)
    console.print("\n[dim]To resume a session, run:[/dim]")
    console.print(f"[bold]make pa session={sessions[0]['id']}[/bold]  [dim](or use any ID above)[/dim]")

if __name__ == "__main__":
    list_sessions()
