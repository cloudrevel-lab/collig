"""
Collig Core Module

Contains core functionality including the reusable interactive menu system.
"""

from .menu import (
    MenuItem,
    MenuAction,
    InteractiveMenu,
    create_simple_menu
)

from .news_cache import (
    NewsCacheEntry,
    NewsCacheManager,
    get_news_cache_manager
)

__all__ = [
    'MenuItem',
    'MenuAction',
    'InteractiveMenu',
    'create_simple_menu',
    'NewsCacheEntry',
    'NewsCacheManager',
    'get_news_cache_manager'
]
