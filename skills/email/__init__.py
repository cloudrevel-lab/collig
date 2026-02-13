from typing import List, Optional, Dict, Any
import imaplib
import smtplib
import email
from email.header import decode_header
from langchain_core.tools import tool, BaseTool
from ..base import Skill
import os
from core.paths import paths
import datetime

try:
    from langchain_openai import OpenAIEmbeddings
    from langchain_chroma import Chroma
    from langchain_core.documents import Document
except ImportError:
    Chroma = None
    OpenAIEmbeddings = None
    Document = None

class EmailSkill(Skill):
    def __init__(self):
        super().__init__()
        # Use a specific config file for email
        self.config_dir = paths.get_skill_config_dir("email")
        self.config_file = os.path.join(self.config_dir, "config.json")

        # Vector Store Init
        self.vectorstore = None
        self.persist_directory = paths.get_skill_data_dir("emails")
        self._initialize_store()

    def _initialize_store(self):
        """Attempts to initialize the vector store if configuration is available."""
        # We need OPENAI_API_KEY for embeddings
        # This might come from global config passed to the skill (self.config)
        # Note: self.config is populated by the Agent when loading skills
        pass

    def _get_vectorstore(self):
        # Lazy initialization because self.config might not be ready at __init__
        if self.vectorstore:
            return self.vectorstore

        api_key = self.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
             # Try loading from global config file directly if not in self.config
            import json
            try:
                with open(paths.global_config_file, "r") as f:
                     g_conf = json.load(f)
                     api_key = g_conf.get("OPENAI_API_KEY")
            except:
                pass

        if api_key and Chroma:
            try:
                self.embeddings = OpenAIEmbeddings(api_key=api_key)
                self.vectorstore = Chroma(
                    persist_directory=self.persist_directory,
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
    def required_config(self) -> List[str]:
        # We don't strictly require top-level keys anymore if we use the accounts dict
        return []

    def get_tools(self) -> List[BaseTool]:

        def _get_account_file(account_name: str) -> str:
            """Returns the file path for a specific account config."""
            # Use URL encoding for email addresses or names
            import urllib.parse
            safe_name = urllib.parse.quote(account_name, safe='')
            return os.path.join(self.config_dir, f"{safe_name}.json")

        def _get_account_config(config: Dict, account_name: Optional[str] = None) -> Dict:
            """Helper to resolve the correct account configuration."""

            # Debugging
            print(f"DEBUG: _get_account_config called with account_name='{account_name}'")

            # If account_name is not provided, try "default"
            target_account = account_name or "default"
            print(f"DEBUG: target_account='{target_account}'")

            # 1. Check if specific account file exists (e.g., 'default.json', 'work.json')
            account_file = _get_account_file(target_account)
            print(f"DEBUG: Checking specific file: {account_file}")
            if os.path.exists(account_file):
                 try:
                    import json
                    with open(account_file, "r") as f:
                        print(f"DEBUG: Found specific file {account_file}")
                        return json.load(f)
                 except Exception as e:
                     print(f"DEBUG: Failed to load {account_file}: {e}")
                     pass

            # 2. If requesting "default" and it doesn't exist, check if there are ANY files in the dir
            if target_account == "default":
                # Ensure directory exists before listing
                if not os.path.exists(self.config_dir):
                    os.makedirs(self.config_dir, exist_ok=True)

                files = [f for f in os.listdir(self.config_dir) if f.endswith(".json")]
                print(f"DEBUG: No specific 'default' file found. Scanning {self.config_dir}. Files: {files}")

                if len(files) > 0:
                     import urllib.parse

                     # Check for specific priority names
                     for priority in ["default.json", "main.json", "personal.json", "work.json"]:
                         if priority in files:
                             try:
                                with open(os.path.join(self.config_dir, priority), "r") as f:
                                    print(f"DEBUG: Found priority file {priority}")
                                    return json.load(f)
                             except:
                                 pass

                     # Fallback: Just pick the first one in the list (which is usually arbitrary but works)
                     try:
                        import json
                        first_file = files[0]
                        print(f"DEBUG: Fallback to first available file: {first_file}")
                        with open(os.path.join(self.config_dir, first_file), "r") as f:
                            return json.load(f)
                     except Exception as e:
                        print(f"DEBUG: Failed to load fallback {first_file}: {e}")
                        pass

            # 3. Fallback to global config (legacy env vars or config.json passed in)
            if config.get("EMAIL_ADDRESS"):
                return {
                    "EMAIL_ADDRESS": config.get("EMAIL_ADDRESS"),
                    "EMAIL_PASSWORD": config.get("EMAIL_PASSWORD"),
                    "IMAP_SERVER": config.get("IMAP_SERVER"),
                    "SMTP_SERVER": config.get("SMTP_SERVER")
                }

            return None

        @tool
        def setup_email(email_address: str, password: str, imap_server: str, smtp_server: str, account_name: str = "default") -> str:
            """
            Configure email settings for the user.
            Args:
                email_address: Full email address (e.g., user@example.com)
                password: Email password or app-specific password.
                imap_server: IMAP server address (e.g., imap.gmail.com).
                smtp_server: SMTP server address (e.g., smtp.gmail.com).
                account_name: Optional name/alias for this account (default: "default").
            """
            import json
            try:
                # IMPORTANT: If account_name is "default", we should check if there is ALREADY an existing single account
                # that is NOT named "default" (e.g. "jacob_cloudrevel.json") and update THAT ONE instead of creating "default.json".
                # This prevents creating a duplicate config when the user just says "update my email".

                target_file_name = account_name

                if account_name == "default":
                    files = [f for f in os.listdir(self.config_dir) if f.endswith(".json")]
                    # Logic update:
                    # If we have 1 file, it's definitely the target.
                    # If we have MULTIPLE files, and one is named "default.json", we should use that.
                    # But if we have multiple files and NONE are "default.json", it's ambiguous which one "default" refers to.
                    # HOWEVER, usually we want to update the *existing* config if we can infer it.

                    if len(files) == 1:
                        import urllib.parse
                        target_file_name = urllib.parse.unquote(files[0].replace(".json", ""))
                    elif len(files) > 1:
                        # Check if "default.json" exists
                        if "default.json" in files:
                            target_file_name = "default"
                        else:
                            # Ambiguous. Let's try to match by email address inside the files?
                            # This is safer. If the user provided an email address, let's find which file contains it.
                            found_match = False
                            for fname in files:
                                try:
                                    with open(os.path.join(self.config_dir, fname), "r") as f:
                                        data = json.load(f)
                                        # Use case-insensitive comparison for email
                                        if data.get("EMAIL_ADDRESS", "").lower() == email_address.lower():
                                            import urllib.parse
                                            target_file_name = urllib.parse.unquote(fname.replace(".json", ""))
                                            found_match = True
                                            break
                                except:
                                    pass

                            if not found_match:
                                # Fallback: if we can't match, we might be creating a new default.
                                # But wait, if we have existing files, we shouldn't overwrite "default" unless explicit.
                                # Let's stick to "default" if no match found, creating a new file.
                                # But if user provided email_address, we should probably name it by email?
                                if email_address:
                                    target_file_name = email_address
                                else:
                                    target_file_name = "default"

                account_data = {
                    "EMAIL_ADDRESS": email_address,
                    "EMAIL_PASSWORD": password,
                    "IMAP_SERVER": imap_server,
                    "SMTP_SERVER": smtp_server
                }

                # Save to specific account file
                account_file = _get_account_file(target_file_name)
                with open(account_file, "w") as f:
                    json.dump(account_data, f, indent=2)

                return f"✅ Email configuration saved for account '{target_file_name}' to {account_file}."
            except Exception as e:
                return f"Failed to save configuration: {e}"

        def _connect_imap(account_config):
            email_user = account_config.get("EMAIL_ADDRESS")
            email_pass = account_config.get("EMAIL_PASSWORD")
            imap_server = account_config.get("IMAP_SERVER")

            if not all([email_user, email_pass, imap_server]):
                raise ValueError("Incomplete email configuration.")

            mail = imaplib.IMAP4_SSL(imap_server)
            mail.login(email_user, email_pass)
            return mail

        @tool
        def check_inbox(limit: int = 5, account_name: str = None) -> str:
            """
            Check recent emails in the inbox.
            Args:
                limit: Number of recent emails to retrieve (default: 5).
                account_name: Optional account alias to use (e.g. "work", "personal"). If not provided, uses the primary account.
            """
            # merged_config logic is now handled inside _get_account_config if we pass self.config
            # but _get_account_config needs to be called.

            # If account_name is "default", treat it as None to trigger the smart fallback logic
            if account_name == "default":
                account_name = None

            account_config = _get_account_config(self.config, account_name)
            if not account_config:
                return f"No email configuration found for account '{account_name or 'default'}'. Please use 'setup_email' tool."

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
                            output.append(f"- [{e_id.decode()}] From: {from_} | Subject: {subject}")

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
                to: Recipient email address.
                subject: Email subject.
                body: Email body content.
                account_name: Optional account alias to use.
            """
            account_config = _get_account_config(self.config, account_name)
            if not account_config:
                return "Missing email configuration. Please use 'setup_email' tool."

            email_user = account_config.get("EMAIL_ADDRESS")
            email_pass = account_config.get("EMAIL_PASSWORD")
            smtp_server = account_config.get("SMTP_SERVER")

            if not all([email_user, email_pass, smtp_server]):
                return "Missing SMTP configuration for this account."

            try:
                server = smtplib.SMTP(smtp_server, 587)
                server.starttls()
                server.login(email_user, email_pass)

                from email.mime.text import MIMEText
                from email.utils import formatdate

                # Create a proper MIME message
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
            Download recent emails and save them to the local vector database for semantic search.
            Args:
                limit: Number of emails to download (default: 20).
                account_name: Optional account alias to use.
            """
            vs = self._get_vectorstore()
            if not vs:
                return "Vector store not initialized. Check OPENAI_API_KEY."

            account_config = _get_account_config(self.config, account_name)
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
                    # Fetch full message
                    status, msg_data = mail.fetch(e_id, "(RFC822)")
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])

                            # Extract Header Info
                            subject, encoding = decode_header(msg["Subject"])[0]
                            if isinstance(subject, bytes):
                                subject = subject.decode(encoding if encoding else "utf-8")

                            sender = msg.get("From")
                            date_str = msg.get("Date")
                            message_id = msg.get("Message-ID", "").strip()

                            # Use Message-ID as unique ID for vector store if available
                            doc_id = message_id if message_id else f"{account_config.get('EMAIL_ADDRESS')}_{e_id.decode()}"

                            # Extract Body
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
                                                # Use HTML if no text/plain found yet
                                                # Ideally strip tags but for now store raw HTML
                                                body = payload
                                        except: pass
                            else:
                                try:
                                    body = msg.get_payload(decode=True).decode()
                                except: pass

                            if not body:
                                body = "[No Text Content]"

                            # Create Document
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
            Search for emails using semantic search (requires previously downloaded emails).
            Args:
                query: Natural language query (e.g. "invoice from HostPapa").
                limit: Number of results.
            """
            vs = self._get_vectorstore()
            if not vs:
                return "Vector store not initialized. Please run 'download_emails' first."

            try:
                results = vs.similarity_search(query, k=limit)
                if not results:
                    return "No matching emails found in local database. Try running 'download_emails' to fetch recent messages."

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
                email_id: Optional ID of the email to read (if known from search/list).
                search_query: Optional query to find the best matching email to read if ID is unknown.
            """
            vs = self._get_vectorstore()
            if not vs:
                return "Vector store not initialized."

            target_doc = None

            # If ID is provided, try to find it (this is a bit tricky with vector store unless we query by metadata)
            # Chroma doesn't have a simple "get by ID" in LangChain interface usually, but we can filter.
            # For simplicity, if search_query is provided, use that.

            if search_query:
                results = vs.similarity_search(search_query, k=1)
                if results:
                    target_doc = results[0]
            elif email_id:
                # Fallback: if user says "read email 1", we might need context of the last search.
                # But since we are stateless here, "1" is meaningless unless we cached the last search.
                # If email_id is a Message-ID (unlikely user types that), we could search.
                # Let's assume user provides a search query like "read email from MYOB".
                return "Please provide a search query to identify the email (e.g., 'read email from MYOB')."

            if target_doc:
                meta = target_doc.metadata
                # Return FULL content (or at least a large chunk)
                # We stored full content in page_content.
                return f"**Subject:** {meta.get('subject')}\n**From:** {meta.get('sender')}\n**Date:** {meta.get('date')}\n\n{target_doc.page_content}"

            return "Email not found."

        return [setup_email, check_inbox, send_email, download_emails, search_emails, read_email]
