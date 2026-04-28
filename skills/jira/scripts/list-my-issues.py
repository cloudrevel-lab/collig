#!/usr/bin/env python3
"""List all open issues assigned to the user across all projects."""

import os
import sys
import base64
import urllib.parse
import json

# Configuration
JIRA_DOMAIN = os.getenv("JIRA_DOMAIN", "nsw-education.atlassian.net")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
ASSIGNEE_ID = "712020:c6ef9d14-053a-42a4-8cb2-10213fc673c7"

BASE_URL = f"https://{JIRA_DOMAIN}/rest/api/3"


def get_auth_header():
    """Create Basic Auth header with email and API token."""
    if not JIRA_EMAIL or not JIRA_API_TOKEN:
        print("Error: JIRA_EMAIL and JIRA_API_TOKEN environment variables must be set")
        sys.exit(1)
    
    credentials = f"{JIRA_EMAIL}:{JIRA_API_TOKEN}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


def get_my_issues():
    """Fetch all open issues assigned to the user."""
    import urllib.request
    
    # JQL: all open issues assigned to user
    jql = f"assignee = '{ASSIGNEE_ID}' AND status != Done ORDER BY updated DESC"
    
    url = f"{BASE_URL}/search?jql={urllib.parse.quote(jql)}&fields=key,summary,status,priority,project,updated"
    
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
        print("No open issues found assigned to you.")
        return
    
    print(f"\n{'='*80}")
    print(f"ALL YOUR OPEN ISSUES")
    print(f"{'='*80}\n")
    
    for issue in issues:
        fields = issue["fields"]
        key = issue["key"]
        summary = fields["summary"]
        status = fields["status"]["name"]
        priority = fields["priority"]["name"] if fields["priority"] else "None"
        project = fields["project"]["name"]
        updated = fields["updated"][:10]  # Just date part
        
        priority_icon = {
            "Highest": "🔴",
            "High": "🟠",
            "Medium": "🟡",
            "Low": "🟢",
            "Lowest": "⚪"
        }.get(priority, "⚪")
        
        print(f"{priority_icon} {key} - {project}")
        print(f"   {summary}")
        print(f"   Status: {status} | Updated: {updated}")
        print()
    
    print(f"Total: {len(issues)} open issue(s)")
    print(f"{'='*80}\n")


def main():
    print("Fetching your open issues from Jira...")
    issues = get_my_issues()
    format_issues(issues)


if __name__ == "__main__":
    main()
