"""
Collig as an ADK app.

ADK's ``AgentLoader`` puts ``agents/`` on ``sys.path`` and imports ``collig``,
so this package is addressed as ``collig`` by the server and as
``agents.collig`` by the CLI. Both resolve to the same ``core.runtime``
singletons, so the two surfaces share one skill registry.
"""
from .agent import app, root_agent

__all__ = ["app", "root_agent"]
