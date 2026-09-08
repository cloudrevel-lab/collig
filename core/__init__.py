"""
Collig Core Module

Contains core functionality including the reusable interactive menu system.

Exports are lazily loaded on first attribute access so that importing a single
submodule (e.g. core.session, core.paths, core.runtime) does not trigger the
entire menu + prompt_toolkit import chain at startup.
"""

__all__ = [
    'MenuItem',
    'MenuAction',
    'InteractiveMenu',
    'create_simple_menu',
    'select_from_menu',
    'NewsCacheEntry',
    'NewsCacheManager',
    'get_news_cache_manager',
]

_lazy_attrs = {
    # name -> (module_path, symbol_name)
    'MenuItem':               ('.menu',            'MenuItem'),
    'MenuAction':             ('.menu',            'MenuAction'),
    'InteractiveMenu':        ('.menu',            'InteractiveMenu'),
    'create_simple_menu':     ('.menu',            'create_simple_menu'),
    'select_from_menu':       ('.menu',            'select_from_menu'),
    'NewsCacheEntry':         ('.news_cache',      'NewsCacheEntry'),
    'NewsCacheManager':       ('.news_cache',      'NewsCacheManager'),
    'get_news_cache_manager': ('.news_cache',      'get_news_cache_manager'),
}


def __getattr__(name):
    if name not in _lazy_attrs:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    module_path, symbol_name = _lazy_attrs[name]
    mod = importlib.import_module(module_path, __name__)
    value = getattr(mod, symbol_name)
    globals()[name] = value
    return value

