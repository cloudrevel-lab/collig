#!/usr/bin/env python3
"""List all issues assigned to the user on the AIE board (current sprint)."""

import os
import sys
import base64
import urllib.parse
import json

# Configuration
JIRA_DOMAIN = os.getenv("JIRA_DOMAIN", "nsw-education.atlassian.net")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
BOARD_ID = "1726"
ASSIGNEE_ID = "712020:c6ef9d14-053a-42a4-8cb2-10213fc673c7"

BASE_URL = f"https://{JIRA_DOMAIN}/rest/api/3"


def get_auth_header():
    """Create Basic Auth header with email and API token."""
    if not JIRA_EMAIL or not JIRA_API_TOKEN:
        print("Error: JIRA_EMAIL and JIRA_API_TOKEN environment variables must be set")
        print("\nSet them with:")
        print('  export JIRA_EMAIL="your.email@education.nsw.gov.au"')
        print('  export JIRA_API_TOKEN="your-token"')
        sys.exit(1)
    
    credentials = f"{JIRA_EMAIL}:{JIRA_API_TOKEN}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


def get_board_issues():
    """Fetch all issues from the board assigned to the user."""
    import urllib.request
    
    # JQL: issues on this board assigned to user
    jql = f"assignee = '{ASSIGNEE_ID}' AND board = {BOARD_ID}"
    
    url = f"{BASE_URL}/search?jql={urllib.parse.quote(jql)}&fields=key,summary,status,priority,assignee"
    
    headers = {
        "Authorization": get_auth_header(),
        "Accept": "application/json"
    }
    
    req = urllib.request.Request(url, headers=headers)
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            return data.get("issues", [])
    except urllib.error.HTTPError as e:
        print(f"Error: HTTP {e.code}")
        print(f"Response: {e.read().decode()}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Error connecting to Jira: {e.reason}")
        sys.exit(1)


def format_issues(issues):
    """Format and display issues in a readable format."""
    if not issues:
        print("No issues found assigned to you on this board.")
        return
    
    print(f"\n{'='*70}")
    print(f"YOUR SPRINT TASKS (Board: {BOARD_ID})")
    print(f"{'='*70}\n")
    
    # Sort by status then priority
    status_order = {"To Do": 0, "In Progress": 1, "Done": 2}
    issues_sorted = sorted(
        issues,
        key=lambda x: (
            status_order.get(x["fields"]["status"]["name"], 99),
            x["fields"]["priority"]["name"] if x["fields"]["priority"] else "Z"
        )
    )
    
    for issue in issues_sorted:
        fields = issue["fields"]
        key = issue["key"]
        summary = fields["summary"]
        status = fields["status"]["name"]
        priority = fields["priority"]["name"] if fields["priority"] else "None"
        
        # Priority icon
        priority_icon = {
            "Highest": "🔴",
            "High": "🟠",
            "Medium": "🟡",
            "Low": "🟢",
            "Lowest": "⚪"
        }.get(priority, "⚪")
        
        # Status icon
        status_icon = {
            "To Do": "⬜",
            "In Progress": "🔄",
            "Done": "✅"
        }.get(status, "◻️")
        
        print(f"{status_icon} {priority_icon} {key}")
        print(f"   {summary}")
        print(f"   Status: {status} | Priority: {priority}")
        print()
    
    print(f"Total: {len(issues)} issue(s)")
    print(f"{'='*70}\n")


def main():
    print("Fetching your sprint tasks from Jira...")
    issues = get_board_issues()
    format_issues(issues)


if __name__ == "__main__":
    main()
