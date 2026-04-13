#!/usr/bin/env python3
"""Test the interactive select menu."""

import sys
sys.path.insert(0, '.')

from core.menu import select_from_menu

# Test the menu
options = [
    "Option 1: Yes, I agree",
    "Option 2: No, I don't agree",
    "Option 3: Maybe later",
    "Option 4: I need more information"
]

print("Testing interactive select menu...")
result = select_from_menu(
    options,
    title="Test Menu",
    subtitle="Please select an option using arrow keys and press Enter"
)

print(f"\nSelected: {result}")
