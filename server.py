from datetime import datetime, timezone
from fastmcp import FastMCP

mcp = FastMCP("LocalWindowsMCP")


@mcp.tool
def ping() -> str:
    """Health check tool to verify the local MCP server is reachable."""
    return f"pong ({datetime.now(timezone.utc).isoformat()})"


@mcp.tool
def add_numbers(a: float, b: float) -> float:
    """Add two numbers together."""
    return a + b


# Expose a standard ASGI app for Uvicorn at /mcp (Streamable HTTP)
app = mcp.http_app(stateless_http=True)
