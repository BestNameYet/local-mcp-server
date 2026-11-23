import asyncio
from datetime import datetime, timezone
from typing import Optional
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from tools.channel import (
    channel as channel_impl,
    format_with_inbox,
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
    """Execute a bash/shell command on the laptop runtime environment."""
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
    """Common Application Namespace for Cross-Agent Communication Channels."""
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


@mcp.custom_route("/bridge/exec", methods=["POST"])
async def bridge_exec(request: Request):
    host = request.headers.get("host", "")
    if not (host.startswith("localhost:") or host.startswith("127.0.0.1:")):
        return JSONResponse({"detail": "Local loopback only"}, status_code=403)
    body = await request.json()
    raw = body.get("code", "")
    lang = body.get("lang", "bash").lower()
    clean = raw.replace("\r\n", "\n").replace("\r", "").strip()
    cmd = ["python3", "-c", clean] if "python" in lang else ["bash", "-c", clean]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=30)
        out, err = out_b.decode(errors="replace"), err_b.decode(errors="replace")
        if out:
            print(f"\n--- [BRIDGE STDOUT] ---\n{out.strip()}", flush=True)
        if err:
            print(f"\n--- [BRIDGE STDERR] ---\n{err.strip()}", flush=True)
        return JSONResponse({"returncode": proc.returncode, "stdout": out, "stderr": err})
    except asyncio.TimeoutError:
        proc.kill()
        return JSONResponse({"returncode": -1, "stdout": "", "stderr": "Execution timed out (30s)"})


app = mcp.http_app(stateless_http=True)
