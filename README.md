# Local Python MCP Server

This repository powers a local [FastMCP](https://gofastmcp.com/) server running on Windows via Uvicorn and exposed through a Cloudflare Tunnel.

## Rules for AI Agents Editing This Repo
1. **Keep tools in `server.py` (or import them into `server.py`)** using the `@mcp.tool` decorator with clear type hints and docstrings.
2. **Do not remove `app = mcp.http_app(stateless_http=True)`** at the bottom of `server.py`—Uvicorn requires `app` to serve the `/mcp` endpoint.
3. **Update `requirements.txt`** whenever you import a new third-party Python package.
4. **Keep tools lightweight** (avoid launching heavy headless browsers unless explicitly requested).
