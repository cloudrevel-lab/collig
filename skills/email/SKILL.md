---
name: Email Manager
description: Manages emails via IMAP/SMTP - read inbox, send emails, and semantic search
version: 1.0.0
author: Collig Team
license: MIT

tools:
  - name: setup_email
    description: Configure email settings for an account
  - name: check_inbox
    description: Check recent emails in the inbox
  - name: send_email
    description: Send an email to a recipient
  - name: download_emails
    description: Download recent emails to local vector database
  - name: search_emails
    description: Search for emails using semantic search
  - name: read_email
    description: Read the full content of a specific email

config:
  required: []
  optional:
    - EMAIL_ADDRESS: Email address for default account
    - EMAIL_PASSWORD: Email password or app-specific password
    - IMAP_SERVER: IMAP server address
    - SMTP_SERVER: SMTP server address
    - LLM_PROVIDER: Provider for embeddings (openai or dashscope)
    - OPENAI_API_KEY: API key for OpenAI embeddings
    - DASHSCOPE_API_KEY: API key for DashScope embeddings

triggers:
  - email
  - mail
  - inbox
  - send email
  - check mail
---

# Email Manager Skill

Provides comprehensive email management capabilities via IMAP/SMTP protocols, including semantic search through downloaded emails.

## Usage

Use this skill when the user wants to:
- Configure email account settings
- Check their inbox for new messages
- Send emails to recipients
- Download and archive emails for later search
- Search through emails using natural language
- Read specific email content

## Examples

- "Set up my email user@gmail.com with password xxx"
- "Check my inbox"
- "Send an email to john@example.com about the meeting"
- "Download my recent emails"
- "Search for emails about the project"
- "Read the email from MYOB"

## Tools

### setup_email(email_address: str, password: str, imap_server: str, smtp_server: str, account_name: str = "default") -> str

Configure email settings for an account.

**Parameters:**
- `email_address`: Full email address (e.g., user@example.com)
- `password`: Email password or app-specific password
- `imap_server`: IMAP server address (e.g., imap.gmail.com)
- `smtp_server`: SMTP server address (e.g., smtp.gmail.com)
- `account_name`: Optional name/alias for this account (default: "default")

**Returns:** Confirmation message or error.

### check_inbox(limit: int = 5, account_name: str = None) -> str

Check recent emails in the inbox.

**Parameters:**
- `limit`: Number of recent emails to retrieve (default: 5)
- `account_name`: Optional account alias to use

**Returns:** Formatted list of recent emails.

### send_email(to: str, subject: str, body: str, account_name: str = None) -> str

Send an email.

**Parameters:**
- `to`: Recipient email address
- `subject`: Email subject
- `body`: Email body content
- `account_name`: Optional account alias to use

**Returns:** Confirmation or error message.

### download_emails(limit: int = 20, account_name: str = None) -> str

Download recent emails and save them to the local vector database for semantic search.

**Parameters:**
- `limit`: Number of emails to download (default: 20)
- `account_name`: Optional account alias to use

**Returns:** Confirmation with count of downloaded emails.

### search_emails(query: str, limit: int = 5) -> str

Search for emails using semantic search.

**Parameters:**
- `query`: Natural language query (e.g. "invoice from HostPapa")
- `limit`: Number of results

**Returns:** Matching emails with summaries.

### read_email(email_id: str = None, search_query: str = None) -> str

Read the full content of a specific email.

**Parameters:**
- `email_id`: Optional ID of the email to read (if known)
- `search_query`: Optional query to find the best matching email

**Returns:** Full email content with headers.

## Notes

- Supports multiple email accounts with named configurations
- Account configs stored in skill config directory
- Vector store requires API key for embeddings (OpenAI or DashScope)
- Semantic search requires emails to be downloaded first
