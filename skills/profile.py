from typing import Dict, Any, List, Optional
import os
import datetime
from langchain_core.tools import tool, BaseTool
from .base import Skill
from core.paths import paths

try:
    from langchain_openai import OpenAIEmbeddings
    from langchain_chroma import Chroma
    from langchain_core.documents import Document
except ImportError:
    Chroma = None
    OpenAIEmbeddings = None

class ProfileSkill(Skill):
    def __init__(self):
        super().__init__()
        self.vectorstore = None
        # Use centralized data directory
        self.persist_directory = paths.get_skill_data_dir("personal_profile")
        
        # Ensure data directory exists
        # os.makedirs(self.persist_directory, exist_ok=True) # Handled by paths

        self._initialize_store()

    @property
    def name(self) -> str:
        return "Personal Profile"

    @property
    def description(self) -> str:
        return "Stores and retrieves personal information about the user (location, preferences, habits, etc.)."

    def _initialize_store(self):
        """Attempts to initialize the vector store if configuration is available."""
        api_key = self.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")

        if not api_key:
            return

        # Initialize Vector Store
        if Chroma and not self.vectorstore:
            try:
                self.embeddings = OpenAIEmbeddings(api_key=api_key)
                self.vectorstore = Chroma(
                    persist_directory=self.persist_directory,
                    embedding_function=self.embeddings,
                    collection_name="user_profile"
                )
            except Exception as e:
                print(f"Failed to initialize Chroma for profile: {e}")

    @property
    def required_config(self) -> List[str]:
        return ["OPENAI_API_KEY"]

    def get_tools(self) -> List[BaseTool]:

        @tool
        def set_personal_info(key: str, value: str, category: str = "general") -> str:
            """
            Save personal information about the user.
            Use this when the user says "set my location to X" or "my name is Y".
            Args:
                key: The attribute name (e.g., "location", "name", "favorite_color").
                value: The value of the attribute (e.g., "Oatlands NSW 2117", "Jacob").
                category: Optional category (e.g., "location", "identity", "preference").
            """
            if not self.vectorstore:
                return "Profile system not initialized. Check OPENAI_API_KEY."

            # Check if key already exists (simple exact match on metadata)
            # This is a bit tricky with vector stores. We might want to "update" logic.
            # But for now, we just add a new document. The retrieval will likely find the most recent or relevant one.
            # To be smarter, we could search for existing key and delete/update it.
            
            # Implementation for "upsert" logic based on key:
            try:
                collection = self.vectorstore._collection
                # Find by key in metadata
                existing = collection.get(where={"key": key})
                if existing and existing['ids']:
                    # Delete existing
                    collection.delete(ids=existing['ids'])
                    # print(f"Updated existing profile entry for '{key}'")

            except Exception as e:
                print(f"Error checking existing profile info: {e}")

            meta = {
                "key": key,
                "category": category,
                "timestamp": datetime.datetime.now().isoformat(),
                "type": "user_profile_attribute"
            }
            
            # Content is structured for semantic search
            content = f"{key}: {value}\nCategory: {category}"
            
            self.vectorstore.add_documents([Document(page_content=content, metadata=meta)])
            return f"✅ Personal info updated: {key} = {value}"

        @tool
        def get_personal_info(query: str) -> str:
            """
            Retrieve personal information about the user based on a query.
            Use this when the user asks "what is my location?" or "do you know my name?".
            Args:
                query: The question or keyword to search for (e.g., "location", "my address").
            """
            if not self.vectorstore:
                return "Profile system not initialized."

            try:
                # Similarity search
                docs = self.vectorstore.similarity_search(query, k=3)
                if not docs:
                    return f"I don't have any information about '{query}' in your profile."
                
                results = []
                for doc in docs:
                    key = doc.metadata.get("key", "unknown")
                    # Parse value from content or store in metadata? 
                    # We stored it as "key: value" in content.
                    # Let's just return the content.
                    results.append(doc.page_content)
                
                return "Here is what I found in your profile:\n" + "\n---\n".join(results)

            except Exception as e:
                return f"Error retrieving personal info: {e}"

        return [set_personal_info, get_personal_info]
