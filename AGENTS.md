# AGENTS.md — Local Python MCP Server Instructions

## 1. Project Overview & Runtime Environment
- **Repository:** `local-mcp-server` (hosted locally on a Windows 11 laptop at `C:\Users\samue\Documents\GitHub\local-mcp-server`).
- **Stack:** Python 3, `fastmcp`, and `uvicorn` (ASGI).
- **Networking:** Exposed publicly via a Cloudflare Named Tunnel forwarding HTTPS traffic to `http://127.0.0.1:8000`.
- **Sync & Deployment Workflow:** Changes pushed to GitHub are pulled locally via GitHub Desktop. The local server runs with `uvicorn server:app --host 127.0.0.1 --port 8000 --reload`, so saving/pulling `.py` files immediately triggers a hot-reload.

## 2. Critical Architectural Rules (Do Not Break)
1. **Entry Point & ASGI App:** Keep `server.py` in the repository root as the main entry point, and **always** preserve `app = mcp.http_app(stateless_http=True)` at the module level so `uvicorn server:app` binds cleanly.
2. **Stateless HTTP Transport:** Always use `stateless_http=True` (Streamable HTTP at `/mcp`). Because `uvicorn --reload` restarts the worker process whenever `git pull` updates code, stateful in-memory session IDs will break active clients.
3. **Cross-Platform Path Safety:** The host OS is Windows 11. Always use `pathlib.Path` instead of hardcoded Unix paths (`/tmp/...`) or backslashes.
4. **Dependency Management:** Any new third-party library imported in code **must** be added to `requirements.txt` in the same commit/PR. Prefer standard library modules (`json`, `pathlib`, `urllib`, `datetime`, `sqlite3`) or lightweight packages (`httpx`, `pydantic`) when possible.

## 3. Hardware & Performance Guardrails
- **Host Constraints:** The host machine has **8 GB total RAM** (~1.5–2.5 GB available headroom).
- **Keep Tools Lightweight:**
  - **Never** launch headless browsers (`selenium`, `playwright`, `puppeteer`), local LLMs, or heavy ML libraries unless explicitly instructed.
  - Use `httpx` or `requests` with explicit timeouts (e.g., `timeout=15.0`) for external API calls.
  - Keep tool responses concise and structured (JSON or compact Markdown) to avoid memory spikes and context-window bloat.
- **Cloudflare Proxy Timeout:** Cloudflare enforces a 100-second HTTP request timeout. Any long-running task (>30 seconds) must run asynchronously in the background and return a job ID or status update immediately rather than blocking the HTTP request.

## 4. Code Structure & Tool Design Standards
- **Modular Organization:** Keep `server.py` clean as the registry/entry point. When adding multiple tools, organize them into modules inside a `tools/` package (e.g., `tools/files.py`, `tools/web.py`) and register/import them in `server.py`.
- **Tool Signatures:**
  - Every `@mcp.tool` function must have full Python type annotations for all parameters and return values.
  - Write clear, action-oriented docstrings explaining *when* to call the tool, what each argument expects, and what the return format looks like.
- **Error Handling:** Never let unhandled exceptions crash the ASGI worker. Catch expected errors (`ValueError`, `FileNotFoundError`, `httpx.HTTPError`) inside tools and return a clear, structured error string or dictionary explaining what went wrong and how the caller can fix its inputs.

## 5. Security & Secrets Rules
- **No Hardcoded Secrets:** Never commit API keys, tokens, passwords, or `.env` files to the repository.
- **Environment Variables:** Read all credentials via `os.getenv("VAR_NAME")`. If a required environment variable is missing, raise or return a descriptive setup message naming the exact variable needed, and document it in `README.md`.
- **Filesystem Boundaries:** Any file-reading or file-writing tool must restrict operations to an explicit allowed workspace directory (using `Path.resolve()`) to prevent accidental path traversal across the Windows filesystem.

## 6. Git & Agent Editing Workflow
- **Verify Before Finishing:** Before finalizing any commit or pull request, verify that:
  1. All imports exist in Python's standard library or `requirements.txt`.
  2. There are no syntax errors or circular imports that would prevent `uvicorn server:app` from reloading cleanly.
  3. `README.md` is updated if new tools, setup steps, or environment variables were added.
