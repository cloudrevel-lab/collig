"""
Map Skill - Provides mapping and location services.
"""
from typing import List
from langchain_core.tools import tool, BaseTool
from skills.base import Skill


class MapSkill(Skill):
    """Provides mapping and location services."""

    def __init__(self, skill_root=None):
        super().__init__(skill_root)

    @property
    def name(self) -> str:
        return "Map"

    @property
    def description(self) -> str:
        return "Provides mapping, directions, and location services"

    @property
    def triggers(self) -> List[str]:
        return ["map", "directions", "location", "where is", "navigate"]

    def get_tools(self) -> List[BaseTool]:

        @tool
        def get_directions(origin: str, destination: str) -> str:
            """
            Get directions between two locations.

            Args:
                origin: Starting location
                destination: Destination location
            """
            # TODO: Implement actual directions API
            return f"Directions from {origin} to {destination}: Mapping service not yet configured."

        @tool
        def search_nearby(location: str, query: str) -> str:
            """
            Search for places near a location.

            Args:
                location: The location to search near
                query: What to search for (e.g., "restaurants", "gas stations")
            """
            # TODO: Implement actual nearby search
            return f"Search for {query} near {location}: Mapping service not yet configured."

        return [get_directions, search_nearby]
