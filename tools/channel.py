"""
tools/channel.py — Communication Channel Abstraction for Cross-Agent Messaging.

Provides a persistent SQLite-backed communication channel namespace where:
- Channels must be explicitly created/registered before use.
- Any operation (subscribe, write, read) against a non-existent channel fails.
- Subscribing an agent ID to a registered channel registers that agent for the channel.
- Any operation (write, read) by an unsubscribed agent ID fails.
- Unread messages across all subscribed channels can be fetched on demand (action='inbox').
- Unread messages are automatically piggybacked onto ANY tool call when an agent ID is supplied
  via the optional 'agent_id' tool parameter or 'X-Agent-ID' HTTP header, completely eliminating polling.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Optional

# Database location: store in data/ directory inside repository
DB_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DB_DIR / "channels.db"


def _get_db() -> sqlite3.Connection:
    """Initialize and return a thread-safe connection to the SQLite database."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """Create the necessary database tables and apply migrations if needed."""
    with conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS channels (
                channel_id TEXT PRIMARY KEY,
                description TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                channel_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                is_subscribed INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (channel_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS read_cursors (
                channel_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                last_read_id INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (channel_id, user_id)
            );

            CREATE INDEX IF NOT EXISTS idx_messages_channel_id ON messages(channel_id, message_id);
            """
        )

        existing_cols = {col[1] for col in conn.execute("PRAGMA table_info(channels)").fetchall()}
        if "description" not in existing_cols:
            conn.execute("ALTER TABLE channels ADD COLUMN description TEXT DEFAULT ''")
        if "created_by" not in existing_cols:
            conn.execute("ALTER TABLE channels ADD COLUMN created_by TEXT DEFAULT ''")


def _now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def get_caller_agent_id(explicit_agent_id: Optional[str] = None) -> Optional[str]:
    """Resolve the caller's agent ID from explicit tool parameter or HTTP headers.

    Checks:
    1. Explicit 'agent_id' passed in tool parameters.
    2. 'X-Agent-ID' or 'Agent-ID' header on the active HTTP request (via FastMCP context).
    """
    if explicit_agent_id and explicit_agent_id.strip():
        return explicit_agent_id.strip()

    try:
        from fastmcp.server.http import _current_http_request
        req = _current_http_request.get()
        if req is not None:
            header_val = req.headers.get("x-agent-id") or req.headers.get("agent-id")
            if header_val and header_val.strip():
                return header_val.strip()
    except Exception:
        pass

    return None


def channel_exists(conn: sqlite3.Connection, channel_id: str) -> bool:
    """Check whether a channel has been explicitly created/registered."""
    cursor = conn.execute(
        "SELECT 1 FROM channels WHERE channel_id = ?",
        (channel_id,),
    )
    return cursor.fetchone() is not None


def is_user_subscribed(conn: sqlite3.Connection, channel_id: str, user_id: str) -> bool:
    """Check whether a user/agent is currently subscribed to a channel."""
    cursor = conn.execute(
        "SELECT is_subscribed FROM subscriptions WHERE channel_id = ? AND user_id = ?",
        (channel_id, user_id),
    )
    row = cursor.fetchone()
    return bool(row and row["is_subscribed"] == 1)


def handle_create(
    channel_id: str,
    description: Optional[str] = None,
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Register and create a new communication channel."""
    clean_id = (channel_id or "").strip()
    if not clean_id:
        return {
            "status": "error",
            "error_code": "INVALID_ARGUMENT",
            "message": "A non-empty 'channel_id' is required to create a channel.",
        }

    now = _now_iso()
    with _get_db() as conn:
        if channel_exists(conn, clean_id):
            return {
                "status": "info",
                "action": "create",
                "channel_id": clean_id,
                "message": f"Channel '{clean_id}' already exists and is active.",
            }

        conn.execute(
            "INSERT INTO channels (channel_id, description, created_by, created_at) VALUES (?, ?, ?, ?)",
            (clean_id, (description or "").strip(), (user_id or "system").strip(), now),
        )

    return {
        "status": "success",
        "action": "create",
        "channel_id": clean_id,
        "description": (description or "").strip(),
        "created_by": user_id or "system",
        "timestamp": now,
        "message": f"Channel '{clean_id}' registered successfully. Subscriptions can now be opened.",
    }


def handle_list(user_id: Optional[str] = None) -> dict[str, Any]:
    """List all registered communication channels and their statuses."""
    with _get_db() as conn:
        rows = conn.execute(
            """
            SELECT c.channel_id, c.description, c.created_by, c.created_at,
                   (SELECT COUNT(*) FROM subscriptions s WHERE s.channel_id = c.channel_id AND s.is_subscribed = 1) AS subscriber_count,
                   (SELECT COUNT(*) FROM messages m WHERE m.channel_id = c.channel_id) AS total_messages
            FROM channels c
            ORDER BY c.created_at ASC
            """
        ).fetchall()

        channels_data = []
        for row in rows:
            is_sub = False
            if user_id:
                is_sub = is_user_subscribed(conn, row["channel_id"], user_id)

            item = {
                "channel_id": row["channel_id"],
                "description": row["description"],
                "created_by": row["created_by"],
                "created_at": row["created_at"],
                "active_subscribers": row["subscriber_count"],
                "total_messages": row["total_messages"],
            }
            if user_id:
                item["is_user_subscribed"] = is_sub
            channels_data.append(item)

    return {
        "status": "success",
        "action": "list",
        "count": len(channels_data),
        "channels": channels_data,
    }


def handle_subscribe(channel_id: str, user_id: str, subscribed: bool) -> dict[str, Any]:
    """Toggle an agent/user's subscription to an existing channel.

    Subscribing inherently registers the agent ID for this channel.
    Fails if the channel has not been created.
    """
    clean_channel = (channel_id or "").strip()
    clean_user = (user_id or "").strip()

    if not clean_channel or not clean_user:
        return {
            "status": "error",
            "error_code": "INVALID_ARGUMENT",
            "message": "Both 'channel_id' and 'user_id' are required.",
        }

    now = _now_iso()
    with _get_db() as conn:
        if not channel_exists(conn, clean_channel):
            return {
                "status": "error",
                "error_code": "CHANNEL_NOT_FOUND",
                "message": (
                    f"Channel '{clean_channel}' does not exist. Only registered channels are valid. "
                    f"Use action='create' with channel_id='{clean_channel}' to register it first."
                ),
            }

        conn.execute(
            """
            INSERT INTO subscriptions (channel_id, user_id, is_subscribed, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(channel_id, user_id) DO UPDATE SET
                is_subscribed = excluded.is_subscribed,
                updated_at = excluded.updated_at
            """,
            (clean_channel, clean_user, 1 if subscribed else 0, now),
        )

    action_text = "subscribed to and registered in" if subscribed else "unsubscribed from"
    return {
        "status": "success",
        "action": "subscribe",
        "channel_id": clean_channel,
        "user_id": clean_user,
        "is_subscribed": subscribed,
        "message": f"Agent '{clean_user}' is now {action_text} channel '{clean_channel}'.",
        "timestamp": now,
    }


def handle_write(channel_id: str, user_id: str, message: str) -> dict[str, Any]:
    """Write a message to a communication channel.

    Fails if the channel does not exist, or if the agent is not subscribed.
    """
    clean_channel = (channel_id or "").strip()
    clean_user = (user_id or "").strip()

    if not clean_channel or not clean_user:
        return {
            "status": "error",
            "error_code": "INVALID_ARGUMENT",
            "message": "Both 'channel_id' and 'user_id' are required.",
        }
    if not message or not message.strip():
        return {
            "status": "error",
            "error_code": "INVALID_ARGUMENT",
            "message": "The 'message' string cannot be empty.",
        }

    with _get_db() as conn:
        if not channel_exists(conn, clean_channel):
            return {
                "status": "error",
                "error_code": "CHANNEL_NOT_FOUND",
                "message": (
                    f"Channel '{clean_channel}' does not exist. Only registered channels can receive messages. "
                    f"Invoke action='create' with channel_id='{clean_channel}' first."
                ),
            }

        if not is_user_subscribed(conn, clean_channel, clean_user):
            return {
                "status": "error",
                "error_code": "NOT_SUBSCRIBED",
                "message": (
                    f"Access denied: Agent '{clean_user}' is not subscribed to channel '{clean_channel}'. "
                    f"Invoke action='subscribe' with channel_id='{clean_channel}', user_id='{clean_user}', subscribed=True first."
                ),
            }

        now = _now_iso()
        cursor = conn.execute(
            "INSERT INTO messages (channel_id, user_id, message, created_at) VALUES (?, ?, ?, ?)",
            (clean_channel, clean_user, message.strip(), now),
        )
        message_id = cursor.lastrowid

    return {
        "status": "success",
        "action": "write",
        "channel_id": clean_channel,
        "user_id": clean_user,
        "message_id": message_id,
        "timestamp": now,
        "message": f"Message #{message_id} posted to channel '{clean_channel}'.",
    }


def handle_read(
    channel_id: str,
    user_id: str,
    i: Optional[int] = 10,
    flag: Optional[str] = "new",
) -> dict[str, Any]:
    """Read messages from a channel.

    Fails if the channel does not exist, or if the agent is not subscribed.
    """
    clean_channel = (channel_id or "").strip()
    clean_user = (user_id or "").strip()

    if not clean_channel or not clean_user:
        return {
            "status": "error",
            "error_code": "INVALID_ARGUMENT",
            "message": "Both 'channel_id' and 'user_id' are required.",
        }

    max_messages = 10 if (i is None or i <= 0) else min(i, 100)
    flag_str = (flag or "new").strip().lower()
    include_old = flag_str in ("new+old", "old", "all", "both", "history")

    with _get_db() as conn:
        if not channel_exists(conn, clean_channel):
            return {
                "status": "error",
                "error_code": "CHANNEL_NOT_FOUND",
                "message": (
                    f"Channel '{clean_channel}' does not exist. Only registered channels can be read. "
                    f"Invoke action='create' with channel_id='{clean_channel}' first."
                ),
            }

        if not is_user_subscribed(conn, clean_channel, clean_user):
            return {
                "status": "error",
                "error_code": "NOT_SUBSCRIBED",
                "message": (
                    f"Access denied: Agent '{clean_user}' is not subscribed to channel '{clean_channel}'. "
                    f"Invoke action='subscribe' with channel_id='{clean_channel}', user_id='{clean_user}', subscribed=True first."
                ),
            }

        cursor_row = conn.execute(
            "SELECT last_read_id FROM read_cursors WHERE channel_id = ? AND user_id = ?",
            (clean_channel, clean_user),
        ).fetchone()
        last_read_id = cursor_row["last_read_id"] if cursor_row else 0

        now = _now_iso()

        if include_old:
            rows = conn.execute(
                """
                SELECT message_id, user_id, message, created_at
                FROM (
                    SELECT message_id, user_id, message, created_at
                    FROM messages
                    WHERE channel_id = ?
                    ORDER BY message_id DESC
                    LIMIT ?
                )
                ORDER BY message_id ASC
                """,
                (clean_channel, max_messages),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT message_id, user_id, message, created_at
                FROM messages
                WHERE channel_id = ? AND message_id > ?
                ORDER BY message_id ASC
                LIMIT ?
                """,
                (clean_channel, last_read_id, max_messages),
            ).fetchall()

        messages = [
            {
                "message_id": row["message_id"],
                "sender": row["user_id"],
                "message": row["message"],
                "created_at": row["created_at"],
                "is_new": row["message_id"] > last_read_id,
            }
            for row in rows
        ]

        if messages:
            new_highest_id = max(m["message_id"] for m in messages)
            updated_cursor_id = max(last_read_id, new_highest_id)
            conn.execute(
                """
                INSERT INTO read_cursors (channel_id, user_id, last_read_id, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(channel_id, user_id) DO UPDATE SET
                    last_read_id = excluded.last_read_id,
                    updated_at = excluded.updated_at
                """,
                (clean_channel, clean_user, updated_cursor_id, now),
            )

        unread_count_row = conn.execute(
            "SELECT COUNT(*) AS unread FROM messages WHERE channel_id = ? AND message_id > ?",
            (clean_channel, max(last_read_id, max((m['message_id'] for m in messages), default=last_read_id))),
        ).fetchone()
        remaining_unread = unread_count_row["unread"] if unread_count_row else 0

    return {
        "status": "success",
        "action": "read",
        "channel_id": clean_channel,
        "user_id": clean_user,
        "mode": "new+old" if include_old else "new",
        "count": len(messages),
        "remaining_unread": remaining_unread,
        "messages": messages,
    }


def handle_inbox(
    user_id: str,
    mark_as_read: bool = True,
    max_per_channel: int = 15,
) -> dict[str, Any]:
    """Retrieve all unread messages across ALL subscribed channels for an agent.

    Advances read cursors when mark_as_read is True, preventing repetitive delivery.
    """
    clean_user = (user_id or "").strip()
    if not clean_user:
        return {
            "status": "error",
            "error_code": "INVALID_ARGUMENT",
            "message": "'user_id' (or 'agent_id') is required to retrieve channel inbox.",
        }

    with _get_db() as conn:
        sub_rows = conn.execute(
            "SELECT channel_id FROM subscriptions WHERE user_id = ? AND is_subscribed = 1",
            (clean_user,),
        ).fetchall()

        if not sub_rows:
            return {
                "status": "success",
                "action": "inbox",
                "user_id": clean_user,
                "total_unread": 0,
                "subscribed_channels": 0,
                "messages": [],
            }

        all_unread = []
        now = _now_iso()

        for sub in sub_rows:
            cid = sub["channel_id"]
            cursor_row = conn.execute(
                "SELECT last_read_id FROM read_cursors WHERE channel_id = ? AND user_id = ?",
                (cid, clean_user),
            ).fetchone()
            last_read_id = cursor_row["last_read_id"] if cursor_row else 0

            msg_rows = conn.execute(
                """
                SELECT message_id, channel_id, user_id AS sender, message, created_at
                FROM messages
                WHERE channel_id = ? AND message_id > ?
                ORDER BY message_id ASC
                LIMIT ?
                """,
                (cid, last_read_id, max_per_channel),
            ).fetchall()

            if msg_rows:
                channel_msgs = [
                    {
                        "channel_id": row["channel_id"],
                        "message_id": row["message_id"],
                        "sender": row["sender"],
                        "message": row["message"],
                        "created_at": row["created_at"],
                    }
                    for row in msg_rows
                ]
                all_unread.extend(channel_msgs)

                if mark_as_read:
                    new_highest = max(m["message_id"] for m in channel_msgs)
                    conn.execute(
                        """
                        INSERT INTO read_cursors (channel_id, user_id, last_read_id, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(channel_id, user_id) DO UPDATE SET
                            last_read_id = excluded.last_read_id,
                            updated_at = excluded.updated_at
                        """,
                        (cid, clean_user, max(last_read_id, new_highest), now),
                    )

    return {
        "status": "success",
        "action": "inbox",
        "user_id": clean_user,
        "total_unread": len(all_unread),
        "subscribed_channels": len(sub_rows),
        "messages": all_unread,
    }


def format_with_inbox(base_result: Any, agent_id: Optional[str] = None) -> str:
    """Format any tool response and automatically piggyback unread channel messages.

    Resolves agent identity via explicit 'agent_id' parameter OR 'X-Agent-ID' HTTP header.
    If the agent has unread messages across any subscribed channel, those messages are attached
    directly to the tool response so the agent receives updates immediately without polling.
    """
    caller_id = get_caller_agent_id(agent_id)
    if not caller_id:
        if isinstance(base_result, (dict, list)):
            return json.dumps(base_result, indent=2)
        return str(base_result)

    inbox = handle_inbox(user_id=caller_id, mark_as_read=True)
    messages = inbox.get("messages", [])

    # If base_result is already a dictionary
    if isinstance(base_result, dict):
        if messages:
            base_result["_channel_inbox"] = {
                "agent_id": caller_id,
                "unread_count": len(messages),
                "messages": messages,
            }
        return json.dumps(base_result, indent=2)

    # If base_result is a JSON string, inject _channel_inbox into the object
    if isinstance(base_result, str):
        try:
            parsed = json.loads(base_result)
            if isinstance(parsed, dict):
                if messages:
                    parsed["_channel_inbox"] = {
                        "agent_id": caller_id,
                        "unread_count": len(messages),
                        "messages": messages,
                    }
                return json.dumps(parsed, indent=2)
        except (json.JSONDecodeError, ValueError):
            pass

    # If base_result is plain text (e.g. "pong (...)" or a calculation result)
    result_str = str(base_result)
    if not messages:
        return result_str

    inbox_lines = [
        f"\n\n--- [CHANNEL INBOX FOR '{caller_id}'] ({len(messages)} unread messages delivered) ---"
    ]
    for m in messages:
        inbox_lines.append(
            f"• [Channel: {m['channel_id']}] from {m['sender']} (msg #{m['message_id']}): {m['message']}"
        )
    inbox_lines.append("-------------------------------------------------------------------------")

    return result_str + "\n".join(inbox_lines)


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
       - Requires: user_id or agent_id (or pass 'X-Agent-ID' header).
    2. 'create' (or 'register'):
       - Register a new valid channel.
       - Requires: channel_id (str). Optional: description (str), user_id (str).
    3. 'list' (or 'list_channels'):
       - List all created/registered channels and subscriber counts.
       - Optional: user_id (str).
    4. 'subscribe':
       - Subscribe (and register) an agent to a valid channel, or unsubscribe.
       - Requires: channel_id (str), user_id (str), subscribed (bool).
       - Fails if channel does not exist.
    5. 'write':
       - Post a message to a channel.
       - Requires: channel_id (str), user_id (str), message (str).
       - Fails if channel does not exist or user is not subscribed.
    6. 'read':
       - Read messages from a channel.
       - Requires: channel_id (str), user_id (str).
       - Optional: i (int, max messages, default 10).
       - Optional: flag (str, 'new' [default] or 'new+old').
       - Fails if channel does not exist or user is not subscribed.

    Args:
        action: The operation: 'inbox', 'create', 'list', 'subscribe', 'write', or 'read'.
        channel_id: The target channel identifier.
        user_id: The agent/user invoking the tool (or agent_id).
        agent_id: Alias for user_id / caller identity.
        subscribed: Required boolean for 'subscribe' (True to join, False to leave).
        message: Required string for 'write'.
        i: Max messages for 'read' (default 10).
        flag: Filter for 'read': 'new' (default) or 'new+old'.
        description: Optional description when creating a channel.

    Returns:
        JSON string containing status, confirmation, or message data.
    """
    clean_action = (action or "").strip().lower()
    effective_user = get_caller_agent_id(user_id or agent_id)

    try:
        if clean_action in ("inbox", "unread"):
            if not effective_user:
                return json.dumps({
                    "status": "error",
                    "error_code": "INVALID_ARGUMENT",
                    "message": "Action 'inbox' requires 'agent_id' (or 'user_id' or 'X-Agent-ID' header)."
                }, indent=2)
            res = handle_inbox(user_id=effective_user, mark_as_read=True)
            return json.dumps(res, indent=2)

        elif clean_action in ("create", "register"):
            if not channel_id:
                return json.dumps({
                    "status": "error",
                    "error_code": "INVALID_ARGUMENT",
                    "message": "Action 'create' requires the 'channel_id' parameter."
                }, indent=2)
            res = handle_create(channel_id=channel_id, description=description, user_id=effective_user)
            return json.dumps(res, indent=2)

        elif clean_action in ("list", "list_channels"):
            res = handle_list(user_id=effective_user)
            return json.dumps(res, indent=2)

        elif clean_action == "subscribe":
            if not channel_id or not effective_user or subscribed is None:
                return json.dumps({
                    "status": "error",
                    "error_code": "INVALID_ARGUMENT",
                    "message": "Action 'subscribe' requires 'channel_id', 'agent_id' (or 'user_id'), and 'subscribed' (bool)."
                }, indent=2)
            res = handle_subscribe(channel_id=channel_id, user_id=effective_user, subscribed=subscribed)
            return json.dumps(res, indent=2)

        elif clean_action == "write":
            if not channel_id or not effective_user or message is None:
                return json.dumps({
                    "status": "error",
                    "error_code": "INVALID_ARGUMENT",
                    "message": "Action 'write' requires 'channel_id', 'agent_id' (or 'user_id'), and 'message' (str)."
                }, indent=2)
            res = handle_write(channel_id=channel_id, user_id=effective_user, message=message)
            return json.dumps(res, indent=2)

        elif clean_action == "read":
            if not channel_id or not effective_user:
                return json.dumps({
                    "status": "error",
                    "error_code": "INVALID_ARGUMENT",
                    "message": "Action 'read' requires 'channel_id' and 'agent_id' (or 'user_id')."
                }, indent=2)
            res = handle_read(channel_id=channel_id, user_id=effective_user, i=i, flag=flag)
            return json.dumps(res, indent=2)

        else:
            return json.dumps({
                "status": "error",
                "error_code": "INVALID_ACTION",
                "message": (
                    f"Unknown action '{action}'. "
                    "Valid actions are: 'inbox', 'create', 'list', 'subscribe', 'write', 'read'."
                )
            }, indent=2)

    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Internal channel error: {str(e)}"
        }, indent=2)
