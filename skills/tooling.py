"""
Tool declaration helpers for Collig skills.

Replaces ``langchain_core.tools.tool``. Google ADK builds a function
declaration straight from a plain function's signature, type hints and
Google-style docstring, so a tool needs no wrapper object -- this decorator
only attaches the metadata the rest of the codebase reads (``.name`` and
``.description``) and hands the function back unchanged.

Keeping tools as plain functions means they stay directly callable::

    tools = skill.get_tools()
    tools[0]("AIE-123")
"""
import inspect
from typing import Any, Callable, Optional

# Replaces ``langchain_core.tools.BaseTool`` in skill type annotations.
# A Collig tool is just a callable carrying ``name``/``description``.
ToolFn = Callable[..., Any]


def tool(func: Optional[Callable] = None, *, name: Optional[str] = None,
         description: Optional[str] = None) -> Any:
    """
    Mark a function as an agent tool.

    Usable bare (``@tool``) or with arguments (``@tool(name="foo")``).
    The function is returned unchanged apart from its metadata:

        name:        the tool name exposed to the LLM (defaults to __name__)
        description: the tool description (defaults to the docstring)

    A ``name`` override also rewrites ``__name__``, since that is what ADK
    reads when it builds the function declaration.
    """
    def decorate(fn: Callable) -> Callable:
        if name:
            setattr(fn, "__name__", name)
        setattr(fn, "name", name or fn.__name__)
        setattr(fn, "description", description or inspect.getdoc(fn) or "")
        setattr(fn, "is_tool", True)
        return fn

    # Bare @tool
    if func is not None:
        return decorate(func)
    # @tool(...)
    return decorate


def tool_name(fn: Any) -> str:
    """Return a tool's name, tolerating undecorated callables."""
    return getattr(fn, "name", None) or getattr(fn, "__name__", str(fn))


def tool_description(fn: Any) -> str:
    """Return a tool's description, tolerating undecorated callables."""
    return getattr(fn, "description", None) or inspect.getdoc(fn) or ""
