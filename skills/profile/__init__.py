"""
Personal Profile skill -- the explicit, model-facing side of user memory.

Automatic capture happens outside the agent turn (``core.runner`` and
``core.user_memory``).  These tools exist for the cases where the user states a
correction or says "remember this" and the model should write it *now*, with a
clear source and category, rather than waiting for the background extractor.

Storage is the shared JSON/Markdown store: no embeddings, no API key beyond the
chat model, readable at ``~/.collig/memory/USER.md``.
"""

from typing import List

from langchain_core.tools import BaseTool, tool

from skills.base import Skill


class ProfileSkill(Skill):
    """Store and retrieve durable personal information about the user."""

    def __init__(self, skill_root=None):
        super().__init__(skill_root)

    def _store(self):
        from core.user_memory import get_user_memory

        return get_user_memory()

    @property
    def name(self) -> str:
        return "Personal Profile"

    @property
    def description(self) -> str:
        return "Remembers durable facts and preferences about the user across sessions"

    @property
    def triggers(self) -> List[str]:
        return [
            "remember this",
            "remember that",
            "save this about me",
            "my preference",
            "personal info",
            "about me",
            "my location",
            "my name",
            "what do you know about me",
        ]

    @property
    def required_config(self) -> List[str]:
        return []

    def get_tools(self) -> List[BaseTool]:

        @tool
        def set_personal_info(key: str, value: str, category: str = "other") -> str:
            """
            Explicitly remember a durable fact about the user.

            Use this when the user says "remember that...", corrects something
            you remembered, or states a preference they will expect you to keep.
            Do not store passwords, API keys, card numbers or other secrets.

            Args:
                key: Stable snake_case attribute name (e.g. "home_location",
                    "name", "daughter_name", "preference_coffee")
                value: The value to remember
                category: identity | location | family | work | preference |
                    routine | project | event | other
            """
            store = self._store()
            fact = store.upsert_fact(
                key,
                value,
                category=(
                    category
                    if category
                    in (
                        "identity",
                        "location",
                        "family",
                        "work",
                        "preference",
                        "routine",
                        "project",
                        "event",
                        "other",
                    )
                    else "other"
                ),
                confidence=0.95,
                source="explicit",
                evidence="User asked Collig to remember this",
            )
            if fact is None:
                return "That looks empty or sensitive, so I did not store it."
            return f"Remembered: {fact['key']} = {fact['value']}"

        @tool
        def get_personal_info(query: str) -> str:
            """
            Look up remembered information about the user.

            Args:
                query: What to look for (e.g. "home city", "daughter", "coffee")
            """
            store = self._store()
            results = store.search(query)
            if not results:
                return f"I do not have anything remembered about '{query}'."
            return "From long-term memory:\n" + "\n".join(
                f"- {fact.get('key')}: {fact.get('value')}" for fact in results
            )

        @tool
        def list_personal_info() -> str:
            """List everything currently remembered about the user."""
            return self._store().summary()

        @tool
        def forget_personal_info(key: str) -> str:
            """
            Forget one remembered fact.

            Args:
                key: The fact key, as shown by list_personal_info
            """
            if self._store().forget(key):
                return f"Forgotten: {key}"
            return f"No remembered fact with key '{key}'."

        @tool
        def record_user_habit(intent: str, description: str, time_of_day: str = "any") -> str:
            """
            Record a recurring routine the user expects you to act on.

            Use this when the user describes a repeated behaviour, for example
            "I check AI news every morning".  A due routine can be acted on
            proactively on a later greeting.

            Args:
                intent: Short intent key such as "news", "weather", "email", "jira"
                description: What the user usually does, in a few words
                time_of_day: any | morning | afternoon | evening | night
            """
            store = self._store()
            store.add_habit(
                intent,
                description,
                time_of_day=time_of_day,
                confidence=0.9,
                source="explicit",
            )
            when = "" if time_of_day in ("any", "") else f" in the {time_of_day}"
            return f"Routine noted: {description}{when}."

        return [
            set_personal_info,
            get_personal_info,
            list_personal_info,
            forget_personal_info,
            record_user_habit,
        ]
