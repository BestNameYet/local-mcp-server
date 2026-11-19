{
  "title": "Local Python MCP Server Architecture, Endpoints, and Operational Reference",
  "applicability": "Apply to any human operator, external AI agent, or MCP client connecting to, starting, verifying, or calling tools on the local-mcp-server runtime hosted on Windows 11 and exposed through a Cloudflare Named Tunnel. For repository code-editing rules, defer to AGENTS.md.",
  "definitions": {
    "local_mcp_server": "A local FastMCP server running on Windows via Uvicorn at http://127.0.0 and exposed publicly at https://dpdns.org.",
    "agent_id": "The unique string identifier representing a caller session (passed via the agent_id tool parameter, the user_id parameter on channel operations, or the X-Agent-ID HTTP header).",
    "piggybacked_channel_inbox": "The server-side zero-polling delivery mechanism that inspects all channels subscribed to by the caller's agent_id during any tool invocation, extracts unread messages, appends them to the tool response, and advances the caller's read cursor in a single turn.",
    "registered_channel": "A persistent SQLite-backed communication channel explicitly created via channel(action='create', channel_id='...'). Operations targeting unregistered channel_ids fail immediately with CHANNEL_NOT_FOUND."
  },
  "environment_and_network_topology": {
    "applicability": "Connecting MCP clients, configuring local runtime environment variables, or inspecting Cloudflare Tunnel routing.",
    "endpoints": {
      "public_cloudflare_tunnel": {
        "url": "https://dpdns.org",
        "purpose": "Public internet streamable HTTP endpoint for remote MCP clients and AI agents (such as Claude Desktop, ChatGPT, or Cursor).",
        "client_configuration_example": {
          "mcpServers": {
            "local-windows-mcp": {
              "url": "https://dpdns.org"
            }
          }
        }
      },
      "local_loopback": {
        "url": "http://127.0.0",
        "purpose": "Local streamable HTTP endpoint running directly on the host laptop."
      }
    },
    "cloudflare_tunnel_specification": {
      "public_hostname": "mcp.x9zk7mp4vn8w.dpdns.org",
      "tunnel_id": "30664c83-c67c-4f6f-a8ad-3416fbd3802a",
      "local_ingress_rule": "Routes traffic from mcp.x9zk7mp4vn8w.dpdns.org to http://127.0.0.1:8000.",
      "config_file_path": "C:\\Users\\samue\\.cloudflared\\config.yml",
      "credentials_file_path": "C:\\Users\\samue\\.cloudflared\\30664c83-c67c-4f6f-a8ad-3416fbd3802a.json"
    },
    "dotenv_configuration": {
      "applicability": "Automatic runtime configuration loading from the repository .env file at server startup.",
      "variables": {
        "HOST": "127.0.0.1",
        "PORT": "8000",
        "CLOUDFLARE_TUNNEL_URL": "https://dpdns.org",
        "CLOUDFLARE_TUNNEL_NAME": "30664c83-c67c-4f6f-a8ad-3416fbd3802a"
      }
    }
  },
  "zero_polling_architecture": {
    "applicability": "Every MCP tool invocation made by an external agent calling local-windows-mcp.",
    "required_behavior": "Include the session's optional agent_id parameter (or X-Agent-ID HTTP header) on every tool call (such as ping, add_numbers, or channel). When agent_id is supplied, the server identifies the caller, extracts unread messages across all subscribed channels, appends them directly to the tool output, and advances the read cursors in a single turn. Use channel(action='inbox', agent_id='...') only when an agent must explicitly check for updates without executing another productive tool.",
    "prohibited_behavior": "Do not execute repeated polling loops against channel(action='inbox') or channel(action='read') while performing other tool calls, because polling wastes LLM tokens, compute, and turns.",
    "piggyback_invocation_example": {
      "request": {
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
      },
      "observed_response": "40.0\n\n--- [CHANNEL INBOX FOR 'coder-1'] (1 unread messages delivered) ---\n• [Channel: ops] from orchestrator (msg #4): Please deploy service v2\n-------------------------------------------------------------------------"
    }
  },
  "cross_agent_communication_channels": {
    "applicability": "Coordinating tasks, status updates, and messages across different ChatGPT sessions (browser or desktop) or autonomous agents using the persistent SQLite-backed channel tool.",
    "strict_prerequisites_and_failure_conditions": [
      {
        "condition": "Channel registration prerequisite",
        "required_behavior": "Only use channel_ids that have been explicitly created via channel(action='create'). Any subscribe, write, or read call targeting an unregistered channel_id fails immediately with CHANNEL_NOT_FOUND."
      },
      {
        "condition": "Agent subscription prerequisite",
        "required_behavior": "Register an agent ID for a channel by invoking channel(action='subscribe', channel_id='...', user_id='...', subscribed=true) on an existing registered channel. Any write or read call made by an unsubscribed agent ID fails immediately with NOT_SUBSCRIBED."
      }
    ],
    "channel_actions": [
      {
        "action": "inbox",
        "applicability": "Retrieving all unread messages across all channels to which the caller agent_id is currently subscribed and marking them as delivered.",
        "parameters": {
          "agent_id": "Required string identifying the agent requesting its inbox."
        }
      },
      {
        "action": "create",
        "applicability": "Creating and registering a new valid communication channel.",
        "parameters": {
          "channel_id": "Required unique string identifier for the channel.",
          "description": "Optional string describing the purpose or topic of the channel.",
          "user_id": "Optional string identifying the creator agent or user."
        }
      },
      {
        "action": "list",
        "applicability": "Listing all registered channels, their subscriber counts, and message statistics.",
        "parameters": {
          "user_id": "Optional string agent ID; when provided, the response includes is_user_subscribed status for each listed channel."
        }
      },
      {
        "action": "subscribe",
        "applicability": "Subscribing an agent to a registered channel (which inherently registers the agent ID) or unsubscribing an agent from that channel.",
        "parameters": {
          "channel_id": "Required string matching an existing registered channel (fails with CHANNEL_NOT_FOUND otherwise).",
          "user_id": "Required string agent or user identifier to subscribe or unsubscribe.",
          "subscribed": "Required boolean specifying subscription state: pass true to subscribe and join the channel, or pass false to unsubscribe and leave the channel."
        }
      },
      {
        "action": "write",
        "applicability": "Posting a message string to a registered channel after confirming the sender agent is subscribed.",
        "parameters": {
          "channel_id": "Required string identifying the registered channel.",
          "user_id": "Required string identifying the subscribed sender agent.",
          "message": "Required string containing the message text to broadcast."
        }
      },
      {
        "action": "read",
        "applicability": "Retrieving messages from a registered channel after confirming the caller agent is subscribed.",
        "parameters": {
          "channel_id": "Required string identifying the registered channel.",
          "user_id": "Required string identifying the subscribed reader agent.",
          "i": "Optional integer specifying maximum number of messages to retrieve (defaults to 10).",
          "flag": "Optional string retrieval mode: pass 'new' (default) to retrieve only unread messages since the last read and advance the read cursor, or pass 'new+old' to retrieve the latest i messages including past history."
        }
      }
    ]
  },
  "startup_and_verification_procedures": {
    "one_click_boot": {
      "applicability": "Starting the local server, Cloudflare Tunnel, and status verification dashboard from Windows Command Prompt or PowerShell.",
      "command": ".\\start_server.bat",
      "required_behavior": "Execute start_server.bat (or boot.bat) to print live progress and the Salient Status Dashboard to the interactive terminal, launch cloudflared.exe, open a companion console window for uvicorn with --reload enabled, execute verify_server.py to test and display all 8 salient statuses (TCP sockets, local and remote MCP handshakes, tool listing, tool execution, and channel operations), and pause with 'Press any key to exit...' so statuses remain visible for inspection."
    },
    "standalone_verification": {
      "applicability": "Verifying the running server and endpoints at any time without restarting processes.",
      "command": ".\\.venv\\Scripts\\python.exe verify_server.py",
      "outcome_verification": "Verification succeeds when verify_server.py reports passing results across all 8 salient status checks for both local loopback and public Cloudflare Tunnel endpoints."
    }
  },
  "governance_cross_reference": {
    "applicability": "Anyone intending to modify source files, add tools, or change dependencies in this repository.",
    "required_behavior": "Consult AGENTS.md for all architectural invariants, hardware memory guardrails, security boundaries, and pre-commit verification rules before editing repository code."
  }
}
