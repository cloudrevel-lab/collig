---
name: jira
description: Interact with Jira API to manage tasks, queries, and sprint work
type: skill
---

## Overview

This skill provides Jira API integration for the NSW Education Jira instance. Use it to query assigned tasks, sprint information, and issue details.

## Configuration

Configure via `/config` command in the interactive console:

1. Run `/config` in the collig console
2. Navigate to the "Skills" tab
3. Find "JIRA" section and set:
   - `JIRA_EMAIL`: Your NSW Education email (e.g., `your.email@education.nsw.gov.au`)
   - `JIRA_API_TOKEN`: Your Atlassian API token

### Getting Your API Token

1. Go to https://id.atlassian.com/manage/api-tokens
2. Click "Create API token"
3. Label it (e.g., "Qwen Code Assistant")
4. Copy the token and paste it in the `/config` screen

## Available Tools

Once configured, you can ask the agent to:

- "What's on my plate this sprint?" - List sprint board tasks
- "Show all my open Jira issues" - List all open issues
- "Get details for AIE-1234" - Get issue details

## Board Configuration

Current board settings (extracted from your Jira URL):
- **Board ID**: 1726
- **Project**: AIE
- **Assignee Filter**: 712020:c6ef9d14-053a-42a4-8cb2-10213fc673c7

## API Endpoints

Base URL: `https://nsw-education.atlassian.net/rest/api/3`

Authentication: Basic Auth with email + API token
