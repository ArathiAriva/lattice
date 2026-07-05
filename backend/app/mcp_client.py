"""
Thin wrapper around the MCP stdio client for the Lattice lookup server.

Provides:
  - mcp_tool_schemas()  → list of OpenAI-format tool dicts (cached after first call)
  - call_mcp_tool()     → execute a named tool, return a JSON string result

The server runs as a subprocess over stdio. Uses the mcp-server venv's python if
present, else the current interpreter (backend requirements include mcp).
"""

import json
import logging
import os
import sys
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger("lattice.mcp_client")

_SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "mcp-server"))
_SERVER_SCRIPT = os.path.join(_SERVER_DIR, "server.py")
_VENV_PYTHON = os.path.join(_SERVER_DIR, ".venv", "bin", "python")

_schema_cache: list[dict] | None = None
_mcp_tool_names: set[str] = set()


def _python() -> str:
    return _VENV_PYTHON if os.path.exists(_VENV_PYTHON) else sys.executable


@asynccontextmanager
async def _mcp_session():
    params = StdioServerParameters(command=_python(), args=[_SERVER_SCRIPT])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def mcp_tool_schemas() -> list[dict]:
    """MCP server tools as OpenAI-compatible schemas. Cached; empty list on failure."""
    global _schema_cache
    if _schema_cache is not None:
        return _schema_cache
    try:
        async with _mcp_session() as session:
            tools = await session.list_tools()
        _schema_cache = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.inputSchema or {"type": "object", "properties": {}},
                },
            }
            for t in tools.tools
        ]
        _mcp_tool_names.update(t.name for t in tools.tools)
        logger.info("MCP tools available: %s", sorted(_mcp_tool_names))
    except Exception:
        logger.exception("MCP server unavailable — continuing without external lookups")
        _schema_cache = []
    return _schema_cache


def is_mcp_tool(name: str) -> bool:
    return name in _mcp_tool_names


async def call_mcp_tool(name: str, args: dict) -> str:
    try:
        async with _mcp_session() as session:
            result = await session.call_tool(name, args)
    except Exception as exc:
        logger.exception("MCP call %s failed", name)
        return json.dumps({"error": f"External lookup failed: {exc}"})
    if result.isError:
        return json.dumps({"error": f"MCP tool error: {name}"})
    parts = [block.text for block in result.content if hasattr(block, "text")]
    combined = " ".join(parts)
    try:
        json.loads(combined)
        return combined
    except json.JSONDecodeError:
        return json.dumps({"result": combined})
