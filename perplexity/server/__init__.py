"""
Perplexity MCP Server package.
Provides both MCP tools and OpenAI-compatible API endpoints.
"""

from .app import mcp, get_pool
from .main import run_server, main

# Import tools to ensure they're registered
from .mcp import list_models, search, research  # noqa: F401

__all__ = ["mcp", "get_pool", "run_server", "main", "list_models", "search", "research"]
