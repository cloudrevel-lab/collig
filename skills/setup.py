from typing import Dict, Any, List
import json
import os
from .base import Skill

from core.paths import paths

class SetupWizardSkill(Skill):
    def __init__(self):
        super().__init__()
        self.state = "IDLE"

    @property
    def name(self) -> str:
        return "Setup Wizard"

    @property
    def description(self) -> str:
        return "Interactive step-by-step guide for configuring skills."

    @property
    def triggers(self) -> List[str]:
        return ["setup", "guide", "help me config", "help me auth", "wizard", "configure"]

    def load_config(self):
        config_file = paths.global_config_file
        if os.path.exists(config_file):
            with open(config_file, "r") as f:
                return json.load(f)
        return {}

    def save_config(self, config):
        with open(paths.global_config_file, "w") as f:
            json.dump(config, f, indent=2)

    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        message = context.get("message", "").lower()

        # RESET logic if user says "cancel" or "stop"
        if message in ["cancel", "stop", "exit", "quit"]:
            self.state = "IDLE"
            return {
                "response": "Setup cancelled. How else can I help you?",
                "action": "stop_setup",
                "status": "done"
            }

        # INITIAL STATE
        if self.state == "IDLE":
            # Detect what to setup
            if "gmail" in message or "email" in message:
                self.state = "GMAIL_CREDS"
                return {
                    "response": (
                        "I can help you setup Gmail access via OAuth 2.0.\n\n"
                        "**Step 1:** You need a `credentials.json` file from Google Cloud Console.\n"
                        "(If you don't have one, create a Desktop App OAuth client ID in Google Cloud Console and download the JSON)\n\n"
                        "Please paste the **full path** to your `credentials.json` file:"
                    ),
                    "action": "ask_input",
                    "status": "continue"
                }
            else:
                # General wizard entry
                self.state = "IDLE" # Remain idle but ask for specific intent next time?
                # Actually, if we want to support general setup, we should switch state.
                self.state = "SELECT_SKILL"
                return {
                    "response": (
                        "I can help you configure the following skills:\n"
                        "1. **Gmail** (Secure OAuth access)\n\n"
                        "Which one would you like to setup? (Type 'gmail')"
                    ),
                    "action": "ask_input",
                    "status": "continue"
                }

        # STATE: SELECT_SKILL
        elif self.state == "SELECT_SKILL":
            if "gmail" in message or "email" in message:
                self.state = "GMAIL_CREDS"
                return {
                    "response": (
                        "Okay, let's setup Gmail.\n\n"
                        "**Step 1:** Please paste the **full path** to your Google Cloud `credentials.json` file:"
                    ),
                    "action": "ask_input",
                    "status": "continue"
                }
            else:
                 return {
                    "response": "I currently only have a wizard for **Gmail**. Please type 'gmail' or 'cancel'.",
                    "action": "ask_input",
                    "status": "continue"
                }

        # STATE: GMAIL_CREDS
        elif self.state == "GMAIL_CREDS":
            path = message.strip()

            # Check for "create" intent or frustration
            if any(w in path for w in ["create", "make", "generate", "build", "do it"]) or ("open" in path and "browser" in path) or ("point" in path and "right place" in path):
                self.state = "GMAIL_BROWSER_OFFER"
                # If explicitly asked to open browser, skip the question and just do it
                if ("open" in path and "browser" in path) or ("point" in path and "right place" in path):
                    self.state = "GMAIL_CREDS" # Go back to waiting for file
                    return {
                        "response": (
                            "Opening Google Cloud Console for you...\n"
                            "Please visit: https://console.cloud.google.com/apis/credentials\n\n"
                            "1. Create a Project.\n2. Create OAuth Client ID (Desktop).\n3. Download JSON.\n\n"
                            "**Once downloaded, paste the full path here:**"
                        ),
                        "action": "open_url",
                        "data": {"url": "https://console.cloud.google.com/apis/credentials"},
                        "status": "continue"
                    }

                return {
                    "response": (
                        "I understand you want me to create the credentials for you.\n\n"
                        "⚠️ **Security Limitation:** I cannot create Google Cloud credentials automatically because it requires:\n"
                        "1. Logging into your personal Google account.\n"
                        "2. Agreeing to Google's Terms of Service.\n"
                        "3. Potentially setting up billing (though Gmail API is free).\n\n"
                        "**I can only help you by guiding you to the right page.**\n\n"
                        "Would you like me to use the **Browser Skill** to open the Google Cloud Console for you? (yes/no)"
                    ),
                    "action": "ask_input",
                    "status": "continue"
                }

            # Check if user said "help" or doesn't have it
            if "help" in path or "don't" in path or "no" in path:
                 return {
                    "response": (
                        "To get the credentials file:\n"
                        "1. Go to https://console.cloud.google.com/\n"
                        "2. Create a new Project.\n"
                        "3. Enable 'Gmail API' in APIs & Services.\n"
                        "4. Go to 'Credentials' -> 'Create Credentials' -> 'OAuth client ID'.\n"
                        "5. Select 'Desktop app'.\n"
                        "6. Download the JSON file.\n\n"
                        "Once you have it, please enter the **full path** to the file:"
                    ),
                    "action": "ask_input",
                    "status": "continue"
                }

            # Handle file path
            # Remove quotes if user added them
            path = path.strip("'\"")
            expanded_path = os.path.expanduser(path)
            # Ensure absolute path for persistence
            absolute_path = os.path.abspath(expanded_path)

            if os.path.exists(absolute_path):
                # Save it
                cfg = self.load_config()
                cfg["gmail_credentials_file"] = absolute_path
                self.save_config(cfg)

                self.state = "GMAIL_AUTH_PROMPT"
                return {
                    "response": (
                        f"✅ Saved credentials path: `{absolute_path}`\n\n"
                        "**Step 2:** Now we need to authenticate.\n"
                        "Shall I run the authentication process now? (yes/no)"
                    ),
                    "action": "confirm",
                    "status": "continue"
                }

            # Check for "yes" to browser open request (from previous turn logic if I had state for it, but I don't.
            # I need to add a sub-state for browser confirmation or handle it here)
            if self.state == "GMAIL_CREDS" and any(w in path for w in ["yes", "sure", "ok", "please"]):
                 # This assumes the user is responding to the "Would you like me to open the browser?" question
                 # But it might also collide with file paths named "yes". Unlikely but possible.
                 # Let's add a specific state transition.
                 pass

            # If not found
            return {
                "response": f"❌ I couldn't find a file at `{path}`.\nPlease check the path and try again (or type 'cancel').\n\nIf you don't have the file yet, ask me for 'help' or to 'create it' for more info.",
                "action": "ask_input",
                "status": "continue"
            }

        # STATE: GMAIL_BROWSER_OFFER (New state)
        elif self.state == "GMAIL_BROWSER_OFFER":
             if "yes" in message or "y" in message or "sure" in message:
                 # Ideally call BrowserSkill here, but we can't invoke another skill directly easily without refactoring.
                 # For now, just return the link.
                 self.state = "GMAIL_CREDS" # Go back to waiting for file
                 return {
                     "response": (
                         "Opening Google Cloud Console...\n"
                         "Please visit: https://console.cloud.google.com/apis/credentials\n\n"
                         "1. Create a Project.\n2. Create OAuth Client ID (Desktop).\n3. Download JSON.\n\n"
                         "**Once downloaded, paste the full path here:**"
                     ),
                     "action": "open_url",
                     "data": {"url": "https://console.cloud.google.com/apis/credentials"},
                     "status": "continue"
                 }
             else:
                 self.state = "GMAIL_CREDS"
                 return {
                     "response": "Okay. Please paste the path to your `credentials.json` file when you have it:",
                     "action": "ask_input",
                     "status": "continue"
                 }

        # STATE: GMAIL_AUTH_PROMPT
        elif self.state == "GMAIL_AUTH_PROMPT":
            if "yes" in message or "y" in message or "sure" in message:
                self.state = "IDLE"
                return {
                    "response": (
                        "Great! I've configured the path.\n\n"
                        "To finish, please run this command:\n"
                        "```\nauth gmail\n```\n"
                        "This will open your browser to login."
                    ),
                    "action": "guide_complete",
                    "status": "done"
                }
            else:
                self.state = "IDLE"
                return {
                    "response": "Okay. You can run `auth gmail` later when you are ready.",
                    "action": "guide_complete",
                    "status": "done"
                }

        # Fallback reset
        self.state = "IDLE"
        return {
            "response": "I'm not sure where we are in the setup. Let's start over.",
            "status": "done"
        }
