from ddgs import DDGS
import json

try:
    print("Testing DDGS news search...")
    # Try positional argument
    results = list(DDGS().news("technology", max_results=5))
    print(f"Found {len(results)} results.")
    for res in results:
        print(f"- {res.get('title')}")
except Exception as e:
    print(f"Error: {e}")
