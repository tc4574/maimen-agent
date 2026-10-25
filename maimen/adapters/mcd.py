"""Official SDK connection and a deliberately small read-only smoke-test boundary."""
import os
from contextlib import asynccontextmanager
from pathlib import Path

ENDPOINT = "https://mcp.mcd.cn"
SMOKE_TOOLS = frozenset({"now-time-info", "list-nutrition-foods"})


def load_token(path=Path(".env")):
    token = os.environ.get("MCD_MCP_TOKEN", "").strip()
    if not token and Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == "MCD_MCP_TOKEN":
                token = value.strip()
                if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
                    token = token[1:-1]
    if not token or any(c.isspace() for c in token) or token.startswith("${"):
        raise ValueError("Missing or invalid MCD_MCP_TOKEN; configure it locally")
    return token


@asynccontextmanager
async def connect(token):
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    async with httpx2.AsyncClient(
        headers={"Authorization": "Bearer " + token},
        timeout=httpx2.Timeout(15.0, read=30.0),
        follow_redirects=False,
    ) as http_client:
        transport = streamable_http_client(ENDPOINT, http_client=http_client)
        async with Client(transport) as client:
            yield client


async def discover(client):
    tools, cursor, seen = [], None, set()
    for _ in range(10):
        page = await client.list_tools(cursor=cursor)
        tools.extend(page.tools)
        if page.next_cursor is None:
            return tools
        cursor = page.next_cursor
        if cursor in seen:
            raise ValueError("Repeated tools cursor")
        seen.add(cursor)
    raise ValueError("Tool discovery page budget exceeded")


async def call_smoke_tool(client, name, arguments, available):
    # SDK metadata is discovery data, not permission to invoke additional tools.
    if name not in SMOKE_TOOLS:
        raise ValueError("Tool outside read-only smoke-test scope")
    tool = next((tool for tool in available if tool.name == name), None)
    if tool is None:
        raise ValueError("Tool not exposed by server")
    from jsonschema import validate
    validate(instance=arguments, schema=tool.input_schema)
    return await client.call_tool(name, arguments)
