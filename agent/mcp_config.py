"""
MCP client configuration + helpers for the Standup Manager Agent.

The agent connects to the standup-tools MCP server (streamable-http) to
perform all deterministic data access (DB reads/writes, Excel rendering,
email sending). Skills call tools directly by name via ainvoke() — these
are fully deterministic pipelines (fetch → reason → save), so no ReAct
tool-selection loop is used; this avoids the risk of an LLM skipping steps,
calling tools out of order, or hallucinating parameters. This mirrors the
reference architecture's own handling of deterministic skills (e.g.
draft_report), which bypasses the ReAct loop for the same reason.
"""
import json
import logging
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

from shared.config import settings

logger = logging.getLogger(__name__)


STANDUP_MCP_CONFIG = {
    "standup-tools": {
        "url": f"{settings.mcp_scheme}://{settings.mcp_host}:{settings.mcp_port}/mcp",
        "transport": "streamable_http",
    }
}


async def get_mcp_tools() -> dict[str, Any]:
    """Discover standup-tools MCP tools, keyed by name."""
    client = MultiServerMCPClient(STANDUP_MCP_CONFIG)
    tools = await client.get_tools()
    return {t.name: t for t in tools}


def parse_mcp_content(content: Any) -> Any:
    """
    Parse an MCP tool result into a Python object.

    langchain_mcp_adapters may return a dict directly, a JSON string, a
    (content, artifact) tuple, or a list of {"type": "text", "text": "..."}
    content blocks depending on the transport/adapter version — handle all.
    """
    if isinstance(content, tuple):
        content = content[0]
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return {}
    if isinstance(content, list):
        parsed_items = []
        for item in content:
            text = None
            if isinstance(item, dict) and "text" in item:
                text = item["text"]
            elif hasattr(item, "text"):
                text = item.text
            elif isinstance(item, str):
                text = item
            if text is not None:
                try:
                    parsed_items.append(json.loads(text))
                except (json.JSONDecodeError, TypeError):
                    continue
        if not parsed_items:
            return {}
        if len(parsed_items) == 1:
            return parsed_items[0]
        return parsed_items
    return {}


async def call_tool(tools: dict[str, Any], name: str, args: dict) -> dict:
    """Invoke a discovered MCP tool by name and return its parsed result dict."""
    tool = tools.get(name)
    if tool is None:
        raise RuntimeError(f"MCP tool '{name}' not found on standup-tools server")
    raw = await tool.ainvoke(args)
    result = parse_mcp_content(raw)
    if isinstance(result, list) and result:
        result = result[0]
    return result if isinstance(result, dict) else {}
