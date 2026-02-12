from typing import Dict, Any, List
import os
from .base import Skill

try:
    import googlemaps
    from datetime import datetime
except ImportError:
    googlemaps = None

class MapSkill(Skill):
    def __init__(self):
        super().__init__()
        self.gmaps = None

    @property
    def name(self) -> str:
        return "Map & Navigation"

    @property
    def description(self) -> str:
        return "Provides directions, routes, and traffic information using Google Maps."

    @property
    def triggers(self) -> List[str]:
        return ["route", "directions", "map", "navigate", "how to get to", "traffic", "distance"]

    @property
    def required_config(self) -> List[str]:
        return ["google_maps_api_key"]

    def _get_client(self):
        if not googlemaps:
            return None
        
        api_key = self.config.get("google_maps_api_key")
        if not api_key:
            return None
            
        if not self.gmaps:
            self.gmaps = googlemaps.Client(key=api_key)
        return self.gmaps

    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        message = context.get("message", "").lower()
        
        # 1. Check Configuration
        client = self._get_client()
        if not client:
            # Fallback to mock/error if no API key
            return {
                "response": (
                    "I need a Google Maps API Key to check real traffic and routes.\n"
                    "Please configure it using: `config set google_maps_api_key YOUR_KEY`"
                ),
                "action": "missing_config"
            }

        # 2. Parse Intent (Origin -> Destination)
        # Simple regex for "from A to B"
        import re
        origin = None
        destination = None
        
        # Pattern: "from [origin] to [destination]"
        match = re.search(r"from\s+(.+?)\s+to\s+(.+)", message)
        if match:
            origin = match.group(1).strip()
            destination = match.group(2).strip()
        else:
            # Try finding just "to [destination]" and assume current location (or ask)
            match_to = re.search(r"to\s+(.+)", message)
            if match_to:
                destination = match_to.group(1).strip()
                origin = "current location" # Placeholder, API requires specific text or lat/lng
        
        if not destination:
             return {
                "response": "I couldn't figure out where you want to go. Please say something like 'route from New York to Boston'.",
                "action": "error"
            }

        try:
            # 3. Call Google Maps API
            now = datetime.now()
            directions_result = client.directions(
                origin,
                destination,
                mode="driving",
                departure_time=now
            )
            
            if not directions_result:
                return {
                    "response": f"I couldn't find a route from '{origin}' to '{destination}'.",
                    "action": "error"
                }
            
            route = directions_result[0]
            leg = route['legs'][0]
            
            duration = leg['duration']['text']
            distance = leg['distance']['text']
            start_address = leg['start_address']
            end_address = leg['end_address']
            
            summary = route.get('summary', 'the best route')
            
            steps = []
            for step in leg['steps'][:3]: # First 3 steps
                import re
                clean_instr = re.sub('<[^<]+?>', '', step['html_instructions']) # Remove HTML tags
                steps.append(f"- {clean_instr} ({step['distance']['text']})")
            
            response_text = (
                f"🚗 **Route from {start_address} to {end_address}**\n"
                f"**Time:** {duration}\n"
                f"**Distance:** {distance}\n"
                f"**Via:** {summary}\n\n"
                "**First few steps:**\n" + "\n".join(steps) + "\n..."
            )

            return {
                "response": response_text,
                "action": "show_route",
                "data": {"route": route}
            }

        except Exception as e:
            return {
                "response": f"Error getting directions: {str(e)}",
                "action": "error"
            }
