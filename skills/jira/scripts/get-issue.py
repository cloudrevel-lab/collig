#!/usr/bin/env python3
"""Get details for a specific Jira issue."""

import os
import sys
import base64
import json

# Configuration
JIRA_DOMAIN = os.getenv("JIRA_DOMAIN", "nsw-education.atlassian.net")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")

BASE_URL = f"https://{JIRA_DOMAIN}/rest/api/3"


def get_auth_header():
    """Create Basic Auth header with email and API token."""
    if not JIRA_EMAIL or not JIRA_API_TOKEN:
        print("Error: JIRA_EMAIL and JIRA_API_TOKEN environment variables must be set")
        sys.exit(1)
    
    credentials = f"{JIRA_EMAIL}:{JIRA_API_TOKEN}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


def get_issue(issue_key):
    """Fetch details for a specific issue."""
    import urllib.request
    
    url = f"{BASE_URL}/issue/{issue_key}?fields=*all"
    
    headers = {
        "Authorization": get_auth_header(),
        "Accept": "application/json"
    }
    
    req = urllib.request.Request(url, headers=headers)
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            return data
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"Error: Issue '{issue_key}' not found")
        else:
            print(f"Error: HTTP {e.code}")
            print(f"Response: {e.read().decode()}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Error connecting to Jira: {e.reason}")
        sys.exit(1)


def format_issue(issue):
    """Format and display issue details."""
    fields = issue["fields"]
    
    print(f"\n{'='*80}")
    print(f"{issue['key']} - {fields.get('summary', 'No summary')}")
    print(f"{'='*80}\n")
    
    # Status and Priority
    status = fields.get("status", {}).get("name", "Unknown")
    priority = fields.get("priority", {}).get("name", "None")
    print(f"Status:   {status}")
    print(f"Priority: {priority}")
    print()
    
    # Assignee
    assignee = fields.get("assignee")
    if assignee:
        print(f"Assignee: {assignee.get('displayName', 'Unassigned')}")
    else:
        print("Assignee: Unassigned")
    
    # Reporter
    reporter = fields.get("reporter")
    if reporter:
        print(f"Reporter: {reporter.get('displayName', 'Unknown')}")
    print()
    
    # Description
    description = fields.get("description")
    if description:
        print("Description:")
        print("-" * 40)
        # Handle Atlassian document format
        if isinstance(description, dict):
            for content in description.get("content", []):
                if content.get("type") == "paragraph":
                    for para in content.get("content", []):
                        print(para.get("text", ""))
        else:
            print(description)
        print()
    
    # Created/Updated
    created = fields.get("created", "")[:10]
    updated = fields.get("updated", "")[:10]
    print(f"Created:  {created}")
    print(f"Updated:  {updated}")
    
    # Subtasks
    subtasks = fields.get("subtasks", [])
    if subtasks:
        print(f"\nSubtasks ({len(subtasks)}):")
        for subtask in subtasks:
            print(f"  - {subtask['key']}: {subtask['fields']['summary']}")
    
    print(f"\n{'='*80}\n")


def main():
    if len(sys.argv) < 2:
        print("Usage: get-issue.py <ISSUE-KEY>")
        print("Example: get-issue.py AIE-1234")
        sys.exit(1)
    
    issue_key = sys.argv[1]
    print(f"Fetching {issue_key} from Jira...")
    issue = get_issue(issue_key)
    format_issue(issue)


if __name__ == "__main__":
    main()
