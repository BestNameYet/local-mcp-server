from datetime import datetime, timezone
import json
from typing import Optional
from fastmcp import FastMCP
from tools.channel import (
    channel as channel_impl,
    format_with_inbox,
    handle_inbox,
)
from tools.terminal import execute_bash

mcp = FastMCP("LocalWindowsMCP")


@mcp.tool
def ping(agent_id: Optional[str] = None) -> str:
    """Health check tool. If agent_id is supplied, unread channel messages are piggybacked."""
    return format_with_inbox(f"pong ({datetime.now(timezone.utc).isoformat()})", agent_id=agent_id)


@mcp.tool
def add_numbers(a: float, b: float, agent_id: Optional[str] = None) -> str:
    """Add two numbers together. If agent_id is supplied, unread channel messages are piggybacked."""
    return format_with_inbox(str(a + b), agent_id=agent_id)


@mcp.tool
def bash(
    command: str,
    cwd: Optional[str] = None,
    agent_id: Optional[str] = None,
    timeout: Optional[float] = 60.0,
) -> str:
    """Execute a bash/shell command on the laptop runtime environment.

    This tool gives agents a full bash terminal emulator backed by the GitHub Desktop
    bundled Git/POSIX toolchain (sh, git, python, grep, sed, awk, ls, find, etc.).
    The working directory defaults to the project repository root.
    GitHub serves as the persistent filesystem: agents can clone, commit, push, pull,
    and branch, making it both a runtime and durable storage layer.

    Use this tool for:
    - Running scripts: 'python my_script.py', 'pytest tests/'
    - Git operations: 'git status', 'git add .', 'git commit -m "..."', 'git push'
    - File inspection: 'ls -la', 'cat README.md', 'grep -r "pattern" .'
    - Multi-command pipelines: 'git log --oneline -5 | grep feat'
    - Installing packages: 'pip install requests'
    - Reading/writing files: 'echo "content" > file.txt', 'cat file.txt'

    Args:
        command: The bash/shell command string to execute.
        cwd: Optional working directory relative to repository root (stays inside repo).
        agent_id: Optional agent identifier. Unread channel messages will be piggybacked
                  onto this response (or pass via 'X-Agent-ID' HTTP header).
        timeout: Max execution time in seconds (default 60, max 90).

    Returns:
        Terminal output including exit code, stdout, stderr, and any piggybacked channel inbox.
    """
    return execute_bash(command=command, cwd=cwd, agent_id=agent_id, timeout=timeout)


@mcp.tool
def channel(
    action: str,
    channel_id: Optional[str] = None,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    subscribed: Optional[bool] = None,
    message: Optional[str] = None,
    i: Optional[int] = 10,
    flag: Optional[str] = "new",
    description: Optional[str] = None,
) -> str:
    """Common Application Namespace for Cross-Agent Communication Channels.

    Use this tool to communicate between ChatGPT sessions, agents, or users.
    Only channels that have been explicitly created/registered are valid.
    Any operation on an unregistered channel fails.
    Subscribing an agent ID inherently registers it for that channel.
    Unsubscribed agents are blocked from writing or reading.

    Supported Actions:
    1. 'inbox' (or 'unread'):
       - Retrieve all unread messages across ALL channels this agent is subscribed to.
       - Requires: agent_id or user_id (or pass 'X-Agent-ID' header).
    2. 'create' (or 'register'):
       - Register a new valid channel.
       - Requires: channel_id (str). Optional: description (str), agent_id (str).
    3. 'list' (or 'list_channels'):
       - List all created/registered channels and subscriber counts.
       - Optional: agent_id (str).
    4. 'subscribe':
       - Subscribe (and register) an agent to a valid channel, or unsubscribe.
       - Requires: channel_id (str), agent_id (str), subscribed (bool).
       - Fails if channel does not exist.
    5. 'write':
       - Post a message to a channel.
       - Requires: channel_id (str), agent_id (str), message (str).
       - Fails if channel does not exist or agent is not subscribed.
    6. 'read':
       - Read messages from a channel.
       - Requires: channel_id (str), agent_id (str).
       - Optional: i (int, max messages, default 10).
       - Optional: flag (str, 'new' [default] or 'new+old').
       - Fails if channel does not exist or agent is not subscribed.

    Args:
        action: The operation: 'inbox', 'create', 'list', 'subscribe', 'write', or 'read'.
        channel_id: The target channel identifier.
        user_id: Agent identifier (alias for agent_id).
        agent_id: Agent identifier for authentication and unread message delivery.
        subscribed: Required boolean for 'subscribe' (True to join, False to leave).
        message: Required string for 'write'.
        i: Max messages for 'read' (default 10).
        flag: Filter for 'read': 'new' (default) or 'new+old'.
        description: Optional description when creating a channel.

    Returns:
        JSON string containing status, confirmation, or message data.
    """
    return channel_impl(
        action=action,
        channel_id=channel_id,
        user_id=user_id,
        agent_id=agent_id,
        subscribed=subscribed,
        message=message,
        i=i,
        flag=flag,
        description=description,
    )


# Expose a standard ASGI app for Uvicorn at /mcp (Streamable HTTP)
app = mcp.http_app(stateless_http=True)
