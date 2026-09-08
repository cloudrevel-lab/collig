"""
Skills package - Portable agent skills following agentskills.io specification.

Exports are lazily loaded on first attribute access so that importing a single
submodule (e.g. skills.manager, skills.builtins) does not trigger the entire
base / manager class chain at module import time.
"""

__all__ = ["Skill", "SkillManager"]

_lazy_attrs = {
    "Skill":        (".base",    "Skill"),
    "SkillManager": (".manager", "SkillManager"),
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
