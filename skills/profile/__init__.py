"""
Personal Profile Skill - Portable implementation following agentskills.io spec.

Stores and retrieves personal information about the user using vector embeddings.
"""
from typing import Dict, Any, List
import os
import datetime
from langchain_core.tools import tool, BaseTool
from skills.base import Skill

try:
    from langchain_openai import OpenAIEmbeddings
    from langchain_chroma import Chroma
    from langchain_core.documents import Document
except ImportError:
    Chroma = None
    OpenAIEmbeddings = None
    Document = None


class ProfileSkill(Skill):
    """Stores and retrieves personal information about the user."""

    def __init__(self, skill_root=None):
        super().__init__(skill_root)
        self.vectorstore = None
        self.persist_directory = None
        self.embeddings = None
        self._initialized = False
        # Don't initialize store here - wait for configure() to be called

    def configure(self, config: Dict[str, Any]):
        """
        Configure the skill and initialize the vector store.
        This is called after the skill is registered and config is available.
        """
        super().configure(config)
        # Re-initialize the store with the new config
        self._initialize_store()

    def _initialize_store(self):
        """Initialize the vector store if configuration is available."""
        # Avoid re-initializing if already done
        if self._initialized and self.vectorstore is not None:
            return

        llm_provider = self.config.get("LLM_PROVIDER", "openai")

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

        if not api_key:
            self._initialized = True
            return

        if Chroma:
            try:
                if base_url:
                    self.embeddings = OpenAIEmbeddings(api_key=api_key, base_url=base_url, model=model_name)
                else:
                    self.embeddings = OpenAIEmbeddings(api_key=api_key, model=model_name)

                persist_dir = self.persist_directory or os.path.join(
                    os.path.expanduser("~"), ".collig", "skills", "profile", "data"
                )
                self.vectorstore = Chroma(
                    persist_directory=persist_dir,
                    embedding_function=self.embeddings,
                    collection_name="user_profile"
                )
                self._initialized = True
            except Exception as e:
                print(f"Failed to initialize Chroma for profile: {e}")
                self._initialized = True
        else:
            self._initialized = True

    @property
    def name(self) -> str:
        return "Personal Profile"

    @property
    def description(self) -> str:
        return "Stores and retrieves personal information about the user"

    @property
    def triggers(self) -> List[str]:
        return ["remember this", "save this about me", "my preference", "personal info", "about me"]

    @property
    def required_config(self) -> List[str]:
        return ["OPENAI_API_KEY", "DASHSCOPE_API_KEY"]

    def get_tools(self) -> List[BaseTool]:

        @tool
        def set_personal_info(key: str, value: str, category: str = "general") -> str:
            """
            Save personal information about the user.
            
            Args:
                key: The attribute name (e.g., "location", "name", "favorite_color")
                value: The value of the attribute
                category: Optional category (e.g., "location", "identity", "preference")
            """
            if not self.vectorstore:
                return "Profile system not initialized. Check API key configuration."

            try:
                collection = self.vectorstore._collection
                existing = collection.get(where={"key": key})
                if existing and existing['ids']:
                    collection.delete(ids=existing['ids'])
            except Exception as e:
                print(f"Error checking existing profile info: {e}")

            meta = {
                "key": key,
                "category": category,
                "timestamp": datetime.datetime.now().isoformat(),
                "type": "user_profile_attribute"
            }

            content = f"User's {key} is {value}. (Category: {category})"
            self.vectorstore.add_documents([Document(page_content=content, metadata=meta)])
            return f"✅ Personal info updated: {key} = {value}"

        @tool
        def get_personal_info(query: str) -> str:
            """
            Retrieve personal information based on a query.
            
            Args:
                query: The question or keyword to search for
            """
            if not self.vectorstore:
                return "Profile system not initialized."

            try:
                docs = self.vectorstore.similarity_search(query, k=5)
                if not docs:
                    return f"I don't have any information about '{query}' in your profile."

                results = []
                for doc in docs:
                    results.append(doc.page_content)

                return "Here is what I found in your profile:\n" + "\n".join(results)
            except Exception as e:
                return f"Error retrieving personal info: {e}"

        return [set_personal_info, get_personal_info]
