"""
Email Manager Skill - Portable implementation following agentskills.io spec.

Manages emails via IMAP/SMTP with semantic search capabilities.
"""
from typing import List, Optional, Dict, Any
import imaplib
import smtplib
import email
from email.header import decode_header
from langchain_core.tools import tool, BaseTool
from skills.base import Skill
import os
import datetime
import json
import urllib.parse

# Heavy vector-store dependencies (langchain_chroma pulls in chromadb, ~0.6s)
# are imported lazily via ``_load_vectorstore_deps`` so importing this module
# at startup stays cheap. They are only needed once email semantic search is actually
# used, which happens well after the CLI is interactive.
Chroma = None
OpenAIEmbeddings = None
Document = None


def _load_vectorstore_deps():
    """Import Chroma/OpenAIEmbeddings/Document on first use. Returns True on success."""
    global Chroma, OpenAIEmbeddings, Document
    if Chroma is not None:
        return True
    try:
        from langchain_openai import OpenAIEmbeddings as _OE
        from langchain_chroma import Chroma as _C
        from langchain_core.documents import Document as _D
        OpenAIEmbeddings, Chroma, Document = _OE, _C, _D
        return True
    except ImportError:
        return False


class EmailSkill(Skill):
    """Manages emails via IMAP/SMTP with semantic search capabilities."""

    def __init__(self, skill_root=None):
        super().__init__(skill_root)
        self.config_dir = None
        self.vectorstore = None
        self.persist_directory = None
        self.embeddings = None

    def _initialize_config_dir(self):
        """Initialize the config directory for email accounts."""
        if self.config_dir:
            return
        
        if self.skill_root and (self.skill_root / "config").exists():
            self.config_dir = self.skill_root / "config"
        else:
            # Fallback to default location
            self.config_dir = None

    def _get_account_file(self, account_name: str) -> str:
        """Returns the file path for a specific account config."""
        if not self.config_dir:
            return ""
        safe_name = urllib.parse.quote(account_name, safe='')
        return os.path.join(self.config_dir, f"{safe_name}.json")

    def _get_account_config(self, account_name: Optional[str] = None) -> Optional[Dict]:
        """Helper to resolve the correct account configuration."""
        if not self.config_dir:
            # Try to get from self.config
            if self.config.get("EMAIL_ADDRESS"):
                return {
                    "EMAIL_ADDRESS": self.config.get("EMAIL_ADDRESS"),
                    "EMAIL_PASSWORD": self.config.get("EMAIL_PASSWORD"),
                    "IMAP_SERVER": self.config.get("IMAP_SERVER"),
                    "SMTP_SERVER": self.config.get("SMTP_SERVER")
                }
            return None

        # If account_name is not provided, try "default"
        target_account = account_name or "default"

        # 1. Check if specific account file exists
        account_file = self._get_account_file(target_account)
        if account_file and os.path.exists(account_file):
            try:
                with open(account_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass

        # 2. If requesting "default" and it doesn't exist, check for any files
        if target_account == "default":
            os.makedirs(self.config_dir, exist_ok=True)
            files = [f for f in os.listdir(self.config_dir) if f.endswith(".json")]

            if len(files) > 0:
                # Check for priority names
                for priority in ["default.json", "main.json", "personal.json", "work.json"]:
                    if priority in files:
                        try:
                            with open(os.path.join(self.config_dir, priority), "r") as f:
                                return json.load(f)
                        except Exception:
                            pass

                # Fallback to first file
                try:
                    with open(os.path.join(self.config_dir, files[0]), "r") as f:
                        return json.load(f)
                except Exception:
                    pass

        return None

    def _get_vectorstore(self):
        """Lazy initialization of the vector store."""
        if self.vectorstore:
            return self.vectorstore

        if not self.config_dir:
            self._initialize_config_dir()

        # Determine which provider is being used
        llm_provider = self.config.get("LLM_PROVIDER", "openai")

        # Get API key and endpoint based on provider
        api_key = None
        base_url = None
        model_name = "text-embedding-ada-002"

        if llm_provider == "dashscope":
            api_key = self.config.get("DASHSCOPE_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
            endpoint_region = self.config.get("DASHSCOPE_ENDPOINT", "china")
            endpoints = {
                "china": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "singapore": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                "international": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
            }
            base_url = endpoints.get(endpoint_region, endpoints["china"])
            model_name = "text-embedding-v2"
        else:
            api_key = self.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")

        if api_key and _load_vectorstore_deps():
            try:
                if base_url:
                    self.embeddings = OpenAIEmbeddings(api_key=api_key, base_url=base_url, model=model_name)
                else:
                    self.embeddings = OpenAIEmbeddings(api_key=api_key, model=model_name)
                
                persist_dir = self.persist_directory or os.path.join(
                    os.path.expanduser("~"), ".collig", "skills", "email", "data"
                )
                self.vectorstore = Chroma(
                    persist_directory=persist_dir,
                    embedding_function=self.embeddings,
                    collection_name="email_archive"
                )
                return self.vectorstore
            except Exception as e:
                print(f"Failed to initialize Chroma for emails: {e}")
        
        return None

    @property
    def name(self) -> str:
        return "Email Manager"

    @property
    def description(self) -> str:
        return "Manages emails via IMAP/SMTP. Can read inbox and send emails."

    @property
    def triggers(self) -> List[str]:
        return ["email", "mail", "inbox", "send email", "check mail"]

    def get_tools(self) -> List[BaseTool]:

        def _connect_imap(account_config: Dict):
            """Connect to IMAP server."""
            email_user = account_config.get("EMAIL_ADDRESS")
            email_pass = account_config.get("EMAIL_PASSWORD")
            imap_server = account_config.get("IMAP_SERVER")

            if not all([email_user, email_pass, imap_server]):
                raise ValueError("Incomplete email configuration.")

            mail = imaplib.IMAP4_SSL(imap_server)
            mail.login(email_user, email_pass)
            return mail

        @tool
        def setup_email(email_address: str, password: str, imap_server: str, smtp_server: str, account_name: str = "default") -> str:
            """
            Configure email settings for an account.
            
            Args:
                email_address: Full email address (e.g., user@example.com)
                password: Email password or app-specific password
                imap_server: IMAP server address (e.g., imap.gmail.com)
                smtp_server: SMTP server address (e.g., smtp.gmail.com)
                account_name: Optional name/alias for this account (default: "default")
            """
            try:
                self._initialize_config_dir()
                
                if not self.config_dir:
                    # Create default config dir
                    self.config_dir = os.path.join(
                        os.path.expanduser("~"), ".collig", "skills", "email", "config"
                    )
                    os.makedirs(self.config_dir, exist_ok=True)

                account_data = {
                    "EMAIL_ADDRESS": email_address,
                    "EMAIL_PASSWORD": password,
                    "IMAP_SERVER": imap_server,
                    "SMTP_SERVER": smtp_server
                }

                account_file = self._get_account_file(account_name)
                with open(account_file, "w") as f:
                    json.dump(account_data, f, indent=2)

                return f"✅ Email configuration saved for account '{account_name}'."
            except Exception as e:
                return f"Failed to save configuration: {e}"

        @tool
        def check_inbox(limit: int = 5, account_name: str = None) -> str:
            """
            Check recent emails in the inbox.
            
            Args:
                limit: Number of recent emails to retrieve (default: 5)
                account_name: Optional account alias to use
            """
            if account_name == "default":
                account_name = None

            account_config = self._get_account_config(account_name)
            if not account_config:
                return "No email configuration found. Please use 'setup_email' tool."

            try:
                mail = _connect_imap(account_config)
                mail.select("inbox")

                status, messages = mail.search(None, "ALL")
                if status != "OK":
                    return "No messages found."

                email_ids = messages[0].split()
                latest_ids = email_ids[-limit:]

                output = [f"Inbox for {account_config.get('EMAIL_ADDRESS')}:"]
                for e_id in reversed(latest_ids):
                    status, msg_data = mail.fetch(e_id, "(RFC822)")
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])
                            subject, encoding = decode_header(msg["Subject"])[0]
                            if isinstance(subject, bytes):
                                subject = subject.decode(encoding if encoding else "utf-8")
                            from_ = msg.get("From")
                            output.append(f"- From: {from_} | Subject: {subject}")

                mail.close()
                mail.logout()
                return "\n".join(output)
            except Exception as e:
                return f"Error checking inbox: {str(e)}"

        @tool
        def send_email(to: str, subject: str, body: str, account_name: str = None) -> str:
            """
            Send an email.
            
            Args:
                to: Recipient email address
                subject: Email subject
                body: Email body content
                account_name: Optional account alias to use
            """
            account_config = self._get_account_config(account_name)
            if not account_config:
                return "Missing email configuration. Please use 'setup_email' tool."

            email_user = account_config.get("EMAIL_ADDRESS")
            email_pass = account_config.get("EMAIL_PASSWORD")
            smtp_server = account_config.get("SMTP_SERVER")

            if not all([email_user, email_pass, smtp_server]):
                return "Missing SMTP configuration."

            try:
                server = smtplib.SMTP(smtp_server, 587)
                server.starttls()
                server.login(email_user, email_pass)

                from email.mime.text import MIMEText
                from email.utils import formatdate

                msg = MIMEText(body)
                msg["Subject"] = subject
                msg["From"] = email_user
                msg["To"] = to
                msg["Date"] = formatdate(localtime=True)

                server.sendmail(email_user, to, msg.as_string())
                server.quit()
                return f"✅ Email sent to {to} from {email_user}"
            except Exception as e:
                return f"Error sending email: {str(e)}"

        @tool
        def download_emails(limit: int = 20, account_name: str = None) -> str:
            """
            Download recent emails and save them to the local vector database.
            
            Args:
                limit: Number of emails to download (default: 20)
                account_name: Optional account alias to use
            """
            vs = self._get_vectorstore()
            if not vs:
                return "Vector store not initialized. Check API key configuration."

            account_config = self._get_account_config(account_name)
            if not account_config:
                return "Missing email configuration."

            try:
                mail = _connect_imap(account_config)
                mail.select("inbox")

                status, messages = mail.search(None, "ALL")
                if status != "OK":
                    return "No messages found."

                email_ids = messages[0].split()
                latest_ids = email_ids[-limit:]

                count = 0
                documents = []

                for e_id in reversed(latest_ids):
                    status, msg_data = mail.fetch(e_id, "(RFC822)")
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])

                            subject, encoding = decode_header(msg["Subject"])[0]
                            if isinstance(subject, bytes):
                                subject = subject.decode(encoding if encoding else "utf-8")

                            sender = msg.get("From")
                            date_str = msg.get("Date")
                            message_id = msg.get("Message-ID", "").strip()

                            doc_id = message_id if message_id else f"{account_config.get('EMAIL_ADDRESS')}_{e_id.decode()}"

                            body = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    content_type = part.get_content_type()
                                    content_disposition = str(part.get("Content-Disposition"))

                                    if "attachment" not in content_disposition:
                                        try:
                                            payload = part.get_payload(decode=True).decode()
                                            if content_type == "text/plain":
                                                body += payload
                                            elif content_type == "text/html" and not body:
                                                body = payload
                                        except Exception:
                                            pass
                            else:
                                try:
                                    body = msg.get_payload(decode=True).decode()
                                except Exception:
                                    pass

                            if not body:
                                body = "[No Text Content]"

                            full_content = f"Subject: {subject}\nFrom: {sender}\nDate: {date_str}\n\n{body}"
                            meta = {
                                "subject": subject,
                                "sender": sender,
                                "date": date_str,
                                "message_id": message_id,
                                "account": account_config.get("EMAIL_ADDRESS"),
                                "timestamp": datetime.datetime.now().isoformat()
                            }

                            documents.append(Document(page_content=full_content, metadata=meta, id=doc_id))
                            count += 1

                if documents:
                    vs.add_documents(documents)

                mail.close()
                mail.logout()
                return f"✅ Downloaded and archived {count} emails."
            except Exception as e:
                return f"Error downloading emails: {e}"

        @tool
        def search_emails(query: str, limit: int = 5) -> str:
            """
            Search for emails using semantic search.
            
            Args:
                query: Natural language query (e.g. "invoice from HostPapa")
                limit: Number of results
            """
            vs = self._get_vectorstore()
            if not vs:
                return "Vector store not initialized. Run 'download_emails' first."

            try:
                results = vs.similarity_search(query, k=limit)
                if not results:
                    return "No matching emails found. Try running 'download_emails'."

                output = [f"Found {len(results)} relevant emails:"]
                for i, doc in enumerate(results, 1):
                    meta = doc.metadata
                    output.append(f"{i}. From: {meta.get('sender')} | Subject: {meta.get('subject')} | Date: {meta.get('date')}")
                    output.append(f"   Summary: {doc.page_content[:200]}...")

                return "\n".join(output)
            except Exception as e:
                return f"Error searching emails: {e}"

        @tool
        def read_email(email_id: str = None, search_query: str = None) -> str:
            """
            Read the full content of a specific email.
            
            Args:
                email_id: Optional ID of the email to read (if known)
                search_query: Optional query to find the best matching email
            """
            vs = self._get_vectorstore()
            if not vs:
                return "Vector store not initialized."

            target_doc = None

            if search_query:
                results = vs.similarity_search(search_query, k=1)
                if results:
                    target_doc = results[0]
            elif email_id:
                return "Please provide a search query to identify the email."

            if target_doc:
                meta = target_doc.metadata
                return f"**Subject:** {meta.get('subject')}\n**From:** {meta.get('sender')}\n**Date:** {meta.get('date')}\n\n{target_doc.page_content}"

            return "Email not found."

        return [setup_email, check_inbox, send_email, download_emails, search_emails, read_email]
