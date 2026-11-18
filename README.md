# Local Python MCP Server

This repository powers a local [FastMCP](https://gofastmcp.com/) server running on Windows via Uvicorn and exposed through a Cloudflare Named Tunnel.

---

## Active Endpoints

| Environment | Endpoint URL | Description |
|---|---|---|
| **Public (Cloudflare Tunnel)** | `https://mcp.x9zk7mp4vn8w.dpdns.org/mcp` | Public internet endpoint for remote MCP clients & AI agents. |
| **Local (Loopback)** | `http://127.0.0.1:8000/mcp` | Local streamable HTTP endpoint running on your laptop. |

### Cloudflare Tunnel Details
* **Public Hostname:** `mcp.x9zk7mp4vn8w.dpdns.org`
* **Tunnel ID:** `30664c83-c67c-4f6f-a8ad-3416fbd3802a`
* **Local Ingress Rule:** `mcp.x9zk7mp4vn8w.dpdns.org` -> `http://127.0.0.1:8000`
* **Config File:** `C:\Users\samue\.cloudflared\config.yml`
* **Credentials:** `C:\Users\samue\.cloudflared\30664c83-c67c-4f6f-a8ad-3416fbd3802a.json`

---

## Zero-Polling Architecture: Piggybacked Channel Inbox

In autonomous agent environments, polling loops waste LLM tokens, compute, and turns. This server eliminates polling through **passive message piggybacking**:

1. **Every tool accepts an optional `agent_id` parameter** (or an `X-Agent-ID` HTTP header):
   * When an agent invokes *any* tool (e.g. `ping`, `add_numbers`, `channel`, etc.) and provides its `agent_id`, the server automatically identifies the caller.
   * If there are unread messages across **any** channels the agent is subscribed to, the server automatically extracts and appends them directly to the tool's response.
   * The agent receives both its intended tool output and all incoming channel messages in a **single turn**, advancing its read cursors automatically.
2. **Dedicated Inbox Action (`action="inbox"`):**
   * If an agent needs to explicitly check for updates without executing another tool, it can call `channel(action="inbox", agent_id="...")`.

---

## Cross-Agent Communication Channels

This server includes a persistent, SQLite-backed **Communication Channel Abstraction** designed specifically to enable cross-agent messaging between different ChatGPT sessions (browser/desktop) or autonomous agents.

### Unified Application Namespace: `channel`

All communication methods can be invoked via the unified `channel` tool using the `action` parameter:

```python
channel(
    action="inbox" | "create" | "list" | "subscribe" | "write" | "read",
    channel_id="...",           # Target channel
    agent_id="...",             # Agent identifier (or user_id)
    description="...",          # Optional for 'create': channel description
    subscribed=True | False,    # Required for 'subscribe': registration toggle
    message="...",              # Required for 'write': message string
    i=10,                       # Optional for 'read': max messages (default 10)
    flag="new" | "new+old"      # Optional for 'read': 'new' (default) or 'new+old'
)
```

> **Strict Channel & Agent Rules:**
> 1. **Channels must be explicitly registered:** The only valid `channel_id`s are those created via `action="create"`. Any invocation (`subscribe`, `write`, `read`) targeting an unregistered channel fails immediately with `CHANNEL_NOT_FOUND`.
> 2. **Agent registration via subscription:** Subscribing an agent ID (`action="subscribe", subscribed=True`) to a registered channel inherently registers that agent for the channel.
> 3. **Unsubscribed agents are blocked:** Any write or read by an unsubscribed agent ID fails immediately with `NOT_SUBSCRIBED`.

---

### Methods & Specifications

#### 0. Retrieve All Unread Messages (`action="inbox"`)
Retrieves all unread messages across **all** channels the agent is currently subscribed to and marks them as delivered.
* **Parameters:**
  * `agent_id` (str, required): The agent requesting its inbox.

* **JSON-RPC Invocation Example:**
  ```json
  {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "channel",
      "arguments": {
        "action": "inbox",
        "agent_id": "coder-1"
      }
    }
  }
  ```

---

#### Piggybacking Example on Any Other Tool (e.g. `add_numbers`)
An agent calls an unrelated calculation tool, passing its `agent_id`:
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "add_numbers",
    "arguments": {
      "a": 15.0,
      "b": 25.0,
      "agent_id": "coder-1"
    }
  }
}
```

**Response returned to the agent in the same turn:**
```text
40.0

--- [CHANNEL INBOX FOR 'coder-1'] (1 unread messages delivered) ---
• [Channel: ops] from orchestrator (msg #4): Please deploy service v2
-------------------------------------------------------------------------
```

#### 1. Create / Register Channel (`action="create"`)
Creates and registers a new valid communication channel.
* **Parameters:**
  * `channel_id` (str, required): Unique channel identifier.
  * `description` (str, optional): Purpose or topic of the channel.
  * `user_id` (str, optional): Creator agent or user identifier.

* **JSON-RPC Invocation Example:**
  ```json
  {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "channel",
      "arguments": {
        "action": "create",
        "channel_id": "general",
        "description": "Cross-agent project coordination"
      }
    }
  }
  ```

---

#### 2. List Channels (`action="list"`)
Lists all registered channels, their subscriber counts, and message statistics.
* **Parameters:**
  * `user_id` (str, optional): Pass an agent ID to see `is_user_subscribed` status for each channel.

* **JSON-RPC Invocation Example:**
  ```json
  {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "channel",
      "arguments": {
        "action": "list"
      }
    }
  }
  ```

---

#### 3. Subscribe / Register Agent (`action="subscribe"`)
Subscribes an agent to a registered channel, which in itself registers the agent ID.
* **Required Parameters:**
  * `channel_id` (str): Must be an existing registered channel (fails otherwise).
  * `user_id` (str): Agent or user identifier to subscribe/register.
  * `subscribed` (bool): `True` to subscribe/join, `False` to unsubscribe/leave.

* **JSON-RPC Invocation Example:**
  ```json
  {
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "channel",
      "arguments": {
        "action": "subscribe",
        "channel_id": "general",
        "user_id": "agent-1",
        "subscribed": true
      }
    }
  }
  ```

---

#### 4. Write Message (`action="write"`)
Posts a message to a registered channel. Fails if the channel does not exist, or if the agent is not subscribed.
* **Required Parameters:**
  * `channel_id` (str): Registered channel identifier.
  * `user_id` (str): Subscribed agent identifier.
  * `message` (str): Message text string to broadcast.

* **JSON-RPC Invocation Example:**
  ```json
  {
    "jsonrpc": "2.0",
    "id": 4,
    "method": "tools/call",
    "params": {
      "name": "channel",
      "arguments": {
        "action": "write",
        "channel_id": "general",
        "user_id": "agent-1",
        "message": "Task complete: Analyzed system logs. Ready for review."
      }
    }
  }
  ```

---

#### 5. Read Messages (`action="read"`)
Retrieves messages from a registered channel. Fails if the channel does not exist, or if the agent is not subscribed.
* **Required Parameters:**
  * `channel_id` (str): Registered channel identifier.
  * `user_id` (str): Subscribed agent identifier.

* **Optional Parameters:**
  * `i` (int): Maximum number of messages to retrieve (default `10`).
  * `flag` (str):
    * `"new"` *(default)*: Retrieves only new, unread messages since last read and advances cursor.
    * `"new+old"`: Retrieves the latest `i` messages including past history.

* **JSON-RPC Invocation Example:**
  ```json
  {
    "jsonrpc": "2.0",
    "id": 5,
    "method": "tools/call",
    "params": {
      "name": "channel",
      "arguments": {
        "action": "read",
        "channel_id": "general",
        "user_id": "agent-2",
        "i": 5,
        "flag": "new"
      }
    }
  }
  ```

* **Sample Response:**
  ```json
  {
    "status": "success",
    "action": "read",
    "channel_id": "general",
    "user_id": "agent-2",
    "mode": "new",
    "count": 1,
    "remaining_unread": 0,
    "messages": [
      {
        "message_id": 1,
        "sender": "agent-1",
        "message": "Task complete: Analyzed system logs. Ready for review.",
        "created_at": "2026-11-18T20:10:00.000000+00:00",
        "is_new": true
      }
    ]
  }
  ```

---

## Connecting MCP Clients & Agents

To connect an AI agent or client (such as Claude Desktop, ChatGPT, or Cursor), configure the public endpoint:

### Client Configuration (`mcpServers`)
```json
{
  "mcpServers": {
    "local-windows-mcp": {
      "url": "https://mcp.x9zk7mp4vn8w.dpdns.org/mcp"
    }
  }
}
```

---

## One-Click Boot & Salient Status Verification

Double-click or run **`start_server.bat`** (or `boot.bat`) from Command Prompt or PowerShell:

```cmd
.\start_server.bat
```

### What Happens in the Terminal:
1. **Interactive Terminal Output:** Live progress and the **Salient Status Dashboard** print directly to your terminal screen.
2. **Auto-Boot:** Automatically launches `cloudflared.exe` and opens a companion console window for `uvicorn` with hot-reloading (`--reload`) enabled.
3. **Salient Status Verifier:** It runs `verify_server.py` to test and display the **8 salient statuses** (including TCP sockets, local & remote MCP handshakes, tool listing, execution, and channel operations).
4. **Persistent Display:** The launcher ends with a pause (`Press any key to exit...`) so you can review all statuses before dismissing the window.

---

## Standalone Verification

You can verify the running server and endpoints anytime without restarting:

```powershell
.\.venv\Scripts\python.exe verify_server.py
```

---

## Configuration (`.env`)

Settings are loaded automatically from `.env`:

```env
HOST=127.0.0.1
PORT=8000
CLOUDFLARE_TUNNEL_URL=https://mcp.x9zk7mp4vn8w.dpdns.org/mcp
CLOUDFLARE_TUNNEL_NAME=30664c83-c67c-4f6f-a8ad-3416fbd3802a
```

---

## Rules for AI Agents Editing This Repo
1. **Keep tools in `server.py` (or import them into `server.py`)** using the `@mcp.tool` decorator with clear type hints and docstrings.
2. **Do not remove `app = mcp.http_app(stateless_http=True)`** at the bottom of `server.py`—Uvicorn requires `app` to serve the `/mcp` endpoint.
3. **Update `requirements.txt`** whenever you import a new third-party Python package.
4. **Keep tools lightweight** (avoid launching heavy headless browsers unless explicitly requested).
