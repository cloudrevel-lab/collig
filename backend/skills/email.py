from typing import Dict, Any, List, Optional
import os.path
import pickle
from .base import Skill

# Google API imports
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

class EmailSkill(Skill):
    def __init__(self):
        super().__init__()
        self.creds = None
        self.service = None

    @property
    def name(self) -> str:
        return "Email Manager"

    @property
    def description(self) -> str:
        return "Checks and manages emails (Gmail) using OAuth 2.0."

    @property
    def triggers(self) -> List[str]:
        return [
            "check my gmail", "check emails", "check email", "read emails", "check my inbox",
            "read email", "open email", "show email", "auth gmail", "authenticate gmail"
        ]

    @property
    def required_config(self) -> List[str]:
        # We need EITHER password (legacy/mock) OR credentials.json path (OAuth)
        return ["gmail_credentials_file"]

    def _get_service(self):
        """Attempts to authenticate and get the Gmail service."""
        if not GOOGLE_API_AVAILABLE:
            return None

        creds = None
        token_path = 'token.pickle'

        # Load existing token
        if os.path.exists(token_path):
            with open(token_path, 'rb') as token:
                creds = pickle.load(token)

        # Refresh or Create new token
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                creds_file = self.config.get("gmail_credentials_file")
                if not creds_file or not os.path.exists(creds_file):
                    return None

                flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
                creds = flow.run_local_server(port=0)

            # Save token
            with open(token_path, 'wb') as token:
                pickle.dump(creds, token)

        return build('gmail', 'v1', credentials=creds)

    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        message = context.get("message", "").lower()

        # Handle explicit authentication request
        if "auth" in message or "authenticate" in message:
            if not self.config.get("gmail_credentials_file"):
                 return {
                    "response": "Please set the 'gmail_credentials_file' config to the path of your Google Cloud credentials.json first.",
                    "action": "missing_config"
                }

            try:
                self.service = self._get_service()
                if self.service:
                     return {
                        "response": "Successfully authenticated with Gmail!",
                        "action": "auth_success"
                    }
                else:
                    return {
                        "response": "Authentication failed. Please check your credentials file.",
                        "action": "auth_failed"
                    }
            except Exception as e:
                return {
                    "response": f"Authentication error: {str(e)}",
                    "action": "error"
                }

        # Try to get service if not already available
        if not self.service:
            try:
                self.service = self._get_service()
            except Exception:
                pass # Fallback to mock if auth fails silently

        # REAL GMAIL API USAGE
        if self.service:
            try:
                # 1. List Messages
                results = self.service.users().messages().list(userId='me', labelIds=['INBOX'], maxResults=5).execute()
                messages = results.get('messages', [])

                if not messages:
                    return {"response": "No new messages found.", "action": "check_email"}

                email_list = []
                for msg in messages:
                    txt = self.service.users().messages().get(userId='me', id=msg['id']).execute()
                    payload = txt['payload']
                    headers = payload.get("headers")
                    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
                    sender = next((h['value'] for h in headers if h['name'] == 'From'), "Unknown")
                    snippet = txt.get('snippet', '')

                    email_list.append(f"- **{subject}** from {sender}\n  _{snippet}_")

                return {
                    "response": "Here are your latest emails:\n\n" + "\n\n".join(email_list),
                    "action": "check_email",
                    "data": {"messages": messages}
                }

            except Exception as e:
                 return {
                    "response": f"Error fetching emails from Gmail: {str(e)}",
                    "action": "error"
                }

        # FALLBACK TO MOCK (if no service)
        # Check configuration for legacy mock
        if not self.config.get("gmail_address") and not self.config.get("gmail_credentials_file"):
            return {
                "response": "Please configure your Gmail address (for mock) or credentials file (for real access). Use the 'config' command.",
                "action": "missing_config"
            }

        # Mock Data
        mock_emails = [
            {"id": 1, "from": "boss@company.com", "subject": "Project Update", "body": "Can you send me the latest report? I need it by EOD. Thanks."},
            {"id": 2, "from": "newsletter@tech.com", "subject": "Weekly Tech News", "body": "Top 10 AI trends you need to know: 1. Agents... 2. LLMs..."},
            {"id": 3, "from": "friend@email.com", "subject": "Dinner tonight?", "body": "Hey, are we still on for 7pm? Let me know!"}
        ]

        # Check if user wants to read a SPECIFIC email
        target_id = None
        import re
        match = re.search(r'\d+', message)
        if match:
            target_id = int(match.group())

        if not target_id:
            if "first" in message: target_id = 1
            elif "second" in message: target_id = 2
            elif "third" in message: target_id = 3

        if target_id is not None:
            email = next((e for e in mock_emails if e["id"] == target_id), None)
            if email:
                return {
                    "response": f"**Subject:** {email['subject']}\n**From:** {email['from']}\n\n{email['body']}",
                    "action": "read_email",
                    "data": {"email": email}
                }
            else:
                return {"response": f"I couldn't find email #{target_id}.", "action": "error"}

        count = len(mock_emails)
        response_text = f"Checking inbox for {self.config.get('gmail_address', 'mock user')}...\n\nYou have {count} new emails:\n"
        for email in mock_emails:
            response_text += f"{email['id']}. From: {email['from']} - Subject: {email['subject']}\n"

        return {
            "response": response_text,
            "action": "check_email",
            "data": {"emails": mock_emails}
        }
