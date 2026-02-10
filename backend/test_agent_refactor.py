import os
import sys

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), "backend"))

# Mock OpenAI API Key for initialization
os.environ["OPENAI_API_KEY"] = "sk-mock-key-for-testing"

from agent import Agent

def test_agent_initialization():
    print("Initializing Agent...")
    agent = Agent()

    print(f"\nRegistered Tools ({len(agent.tools)}):")
    for tool in agent.tools:
        print(f" - {tool.name}: {tool.description}")

    expected_tools = [
        "get_current_time", "open_browser", "get_weather",
        "create_directory", "list_directory", "delete_item", "write_file", "read_file",
        "get_system_status",
        "add_note", "list_notes", "search_notes", "delete_notes",
        "add_bookmark", "list_bookmarks", "search_bookmarks", "delete_bookmarks"
    ]

    tool_names = [t.name for t in agent.tools]
    missing = [t for t in expected_tools if t not in tool_names]

    if missing:
        print(f"\n❌ Missing expected tools: {missing}")
    else:
        print("\n✅ All expected tools registered successfully.")

if __name__ == "__main__":
    test_agent_initialization()
