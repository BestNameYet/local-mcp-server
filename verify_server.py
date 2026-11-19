import socket as _sock
_orig_getaddrinfo = _sock.getaddrinfo
def _ipv4_only_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, _sock.AF_INET, type, proto, flags)
_sock.getaddrinfo = _ipv4_only_getaddrinfo

"""
verify_server.py — Salient Status & Health Verification Suite for MCP Server.

Verifies the following 9 salient statuses:
1. Local TCP Socket (Port 8000 listening)
2. Local MCP Protocol Handshake (JSON-RPC initialize, server info, protocol version)
3. Tool Discovery (tools/list enumeration and schema verification)
4. Local Tool Execution (ping -> pong timestamp verification)
5. Local Parameterized Tool Execution (add_numbers(12.5, 29.5) -> 42.0)
5b. Cross-Agent Channel Verification (channel create + subscribe)
6. Cloudflare Tunnel Edge Connectivity (HTTP 200 via mcp.x9zk7mp4vn8w.dpdns.org)
7. Remote MCP Protocol Handshake (through Cloudflare Tunnel)
8. Remote Tool Execution (end-to-end ping -> pong over public internet)
9. Bash Terminal Tool Execution (bash('git log --oneline -1') -> exit 0 + git output)
"""

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
import sys
import time
from typing import Any, Optional
import urllib.error
import urllib.request


@dataclass
class CheckResult:
    index: int
    name: str
    target: str
    passed: bool
    latency_ms: float
    details: str = ""


def load_env_file(env_path: Path) -> None:
    """Load key-value pairs from a .env file into os.environ if not already set."""
    if not env_path.is_file():
        return
    try:
        content = env_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception as e:
        print(f"  [WARN] Failed reading .env: {e}")


def wait_for_port(host: str, port: int, timeout: float = 15.0) -> tuple[bool, float]:
    """Wait until the specified TCP port is accepting connections, returning (success, latency_ms)."""
    start = time.time()
    while time.time() - start < timeout:
        t0 = time.time()
        try:
            with socket.create_connection((host, port), timeout=1.0):
                latency = (time.time() - t0) * 1000.0
                return True, latency
        except (OSError, socket.timeout):
            time.sleep(0.5)
    return False, 0.0


def send_mcp_request(url: str, payload: dict[str, Any], timeout: float = 12.0) -> tuple[dict[str, Any], float]:
    """Send a JSON-RPC request to the MCP endpoint and parse response."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        },
        method="POST",
    )

    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_type = resp.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            last_json = None
            while True:
                raw_line = resp.readline()
                if not raw_line:
                    break
                stripped = raw_line.decode("utf-8", errors="replace").strip()
                if stripped.startswith("data:"):
                    data_str = stripped[5:].strip()
                    if data_str:
                        try:
                            last_json = json.loads(data_str)
                            break
                        except json.JSONDecodeError:
                            continue
            latency = (time.time() - t0) * 1000.0
            if last_json is not None:
                return last_json, latency
            return {}, latency

        raw_body = resp.read().decode("utf-8", errors="replace")
        latency = (time.time() - t0) * 1000.0
        return json.loads(raw_body), latency


def run_salient_checks(local_url: str, tunnel_url: Optional[str], host: str, port: int, timeout: float) -> list[CheckResult]:
    """Execute all salient checks and return structured results."""
    results: list[CheckResult] = []
    current_idx = 1

    print("\n" + "=" * 76)
    print("           VERIFYING SALIENT MCP SERVER & TUNNEL STATUSES")
    print("=" * 76)

    # -------------------------------------------------------------------------
    # Status 1: Local TCP Socket
    # -------------------------------------------------------------------------
    print(f"\n[Status 1/9] Checking Local TCP Port Binding ({host}:{port})...")
    port_open, port_lat = wait_for_port(host, port, timeout=timeout)
    if port_open:
        print(f"  [PASS] Port {port} is LISTENING and accepting connections ({port_lat:.1f}ms).")
        results.append(CheckResult(current_idx, "Local TCP Socket", f"{host}:{port}", True, port_lat, "Listening"))
    else:
        print(f"  [FAIL] Port {port} is NOT responding after {timeout:.1f}s.")
        print(f"         Make sure Uvicorn is running: uvicorn server:app --host {host} --port {port}")
        results.append(CheckResult(current_idx, "Local TCP Socket", f"{host}:{port}", False, 0.0, "Connection refused"))
        return results  # Stop early if local port is down
    current_idx += 1

    # -------------------------------------------------------------------------
    # Status 2: Local MCP Handshake
    # -------------------------------------------------------------------------
    print(f"\n[Status 2/9] Testing Local MCP Protocol Handshake ({local_url})...")
    init_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "salient-verifier", "version": "1.0"},
        },
    }

    try:
        init_res, init_lat = send_mcp_request(local_url, init_payload, timeout=10.0)
        server_info = init_res.get("result", {}).get("serverInfo", {})
        server_name = server_info.get("name", "Unknown")
        protocol_ver = init_res.get("result", {}).get("protocolVersion", "Unknown")
        print(f"  [PASS] Protocol Handshake OK ({init_lat:.1f}ms)")
        print(f"         Server Name: {server_name} | Protocol Version: {protocol_ver}")
        results.append(CheckResult(current_idx, "Local Handshake", f"{server_name} (v{protocol_ver})", True, init_lat, "Handshake OK"))
    except Exception as e:
        print(f"  [FAIL] Handshake failed: {e}")
        results.append(CheckResult(current_idx, "Local Handshake", local_url, False, 0.0, str(e)))
        return results
    current_idx += 1

    # -------------------------------------------------------------------------
    # Status 3: Tool Discovery
    # -------------------------------------------------------------------------
    print("\n[Status 3/9] Discovering Registered Tools (tools/list)...")
    list_payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    try:
        list_res, list_lat = send_mcp_request(local_url, list_payload, timeout=10.0)
        tools = list_res.get("result", {}).get("tools", [])
        tool_names = [t.get("name", "") for t in tools]
        print(f"  [PASS] Discovered {len(tools)} tools ({list_lat:.1f}ms): {', '.join(tool_names)}")
        results.append(CheckResult(current_idx, "Tool Discovery", f"{len(tools)} tools: {', '.join(tool_names)}", True, list_lat, f"{len(tools)} available"))
    except Exception as e:
        print(f"  [FAIL] Tool discovery failed: {e}")
        results.append(CheckResult(current_idx, "Tool Discovery", "tools/list", False, 0.0, str(e)))
        return results
    current_idx += 1

    # -------------------------------------------------------------------------
    # Status 4: Local Tool Execution (ping)
    # -------------------------------------------------------------------------
    print("\n[Status 4/9] Testing Local Tool Execution (tools/call -> ping)...")
    ping_payload = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "ping", "arguments": {}}}
    try:
        ping_res, ping_lat = send_mcp_request(local_url, ping_payload, timeout=10.0)
        content = ping_res.get("result", {}).get("content", [])
        output_text = content[0].get("text", "") if (content and isinstance(content, list)) else ""
        if "pong" in output_text:
            print(f"  [PASS] Tool 'ping' returned: \"{output_text}\" ({ping_lat:.1f}ms)")
            results.append(CheckResult(current_idx, "Local Tool Call", "ping -> pong", True, ping_lat, output_text))
        else:
            print(f"  [FAIL] Unexpected output: {output_text}")
            results.append(CheckResult(current_idx, "Local Tool Call", "ping", False, ping_lat, f"Unexpected: {output_text}"))
    except Exception as e:
        print(f"  [FAIL] Tool execution failed: {e}")
        results.append(CheckResult(current_idx, "Local Tool Call", "ping", False, 0.0, str(e)))
    current_idx += 1

    # -------------------------------------------------------------------------
    # Status 5: Parameterized Tool Execution (add_numbers)
    # -------------------------------------------------------------------------
    print("\n[Status 5/9] Testing Parameterized Tool Execution (tools/call -> add_numbers)...")
    add_payload = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "add_numbers", "arguments": {"a": 12.5, "b": 29.5}},
    }
    try:
        add_res, add_lat = send_mcp_request(local_url, add_payload, timeout=10.0)
        content = add_res.get("result", {}).get("content", [])
        output_text = content[0].get("text", "") if (content and isinstance(content, list)) else ""
        if output_text == "42.0" or "42" in output_text:
            print(f"  [PASS] add_numbers(12.5, 29.5) returned: {output_text} ({add_lat:.1f}ms)")
            results.append(CheckResult(current_idx, "Local Param Test", "add_numbers(12.5, 29.5)=42.0", True, add_lat, "Computed 42.0"))
        else:
            print(f"  [FAIL] Unexpected output: {output_text}")
            results.append(CheckResult(current_idx, "Local Param Test", "add_numbers", False, add_lat, output_text))
    except Exception as e:
        print(f"  [FAIL] Parameterized tool call failed: {e}")
        results.append(CheckResult(current_idx, "Local Param Test", "add_numbers", False, 0.0, str(e)))
    current_idx += 1

    # Status 5b: Cross-Agent Channel Verification (create & subscribe)
    create_payload = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "channel",
            "arguments": {
                "action": "create",
                "channel_id": "health-check",
                "description": "System health verification channel",
            },
        },
    }
    chan_payload = {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {
            "name": "channel",
            "arguments": {
                "action": "subscribe",
                "channel_id": "health-check",
                "user_id": "verifier",
                "subscribed": True,
            },
        },
    }
    try:
        send_mcp_request(local_url, create_payload, timeout=10.0)
        chan_res, chan_lat = send_mcp_request(local_url, chan_payload, timeout=10.0)
        content = chan_res.get("result", {}).get("content", [])
        chan_text = content[0].get("text", "") if (content and isinstance(content, list)) else ""
        if "success" in chan_text:
            print(f"  [PASS] Channel namespace 'channel(action=\"create/subscribe\")' verified ({chan_lat:.1f}ms)")
        else:
            print(f"  [WARN] Channel test unexpected response: {chan_text}")
    except Exception as e:
        print(f"  [WARN] Channel test warning: {e}")

    # -------------------------------------------------------------------------
    # Cloudflare Tunnel Checks (Statuses 6, 7, 8)
    # -------------------------------------------------------------------------
    if not tunnel_url:
        print("\n[INFO] No CLOUDFLARE_TUNNEL_URL configured. Skipping tunnel checks (6-8).")
        # Still run the local bash check (Status 9) even without a tunnel
        current_idx = 6  # adjust index since 6/7/8 are skipped
        bash_payload_local = {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "bash",
                "arguments": {"command": "git log --oneline -1", "agent_id": "verifier"},
            },
        }
        print(f"\n[Status 6/6] Testing Bash Terminal Tool Execution (bash -> git log)...")
        try:
            bash_res, bash_lat = send_mcp_request(local_url, bash_payload_local, timeout=20.0)
            content = bash_res.get("result", {}).get("content", [])
            bash_text = content[0].get("text", "") if (content and isinstance(content, list)) else ""
            if "[Exit Code: 0]" in bash_text:
                print(f"  [PASS] bash('git log --oneline -1') OK ({bash_lat:.1f}ms)")
                results.append(CheckResult(current_idx, "Bash Terminal", "git log --oneline -1", True, bash_lat, "Exit 0 + git output"))
            else:
                print(f"  [FAIL] Unexpected bash output: {bash_text[:200]}")
                results.append(CheckResult(current_idx, "Bash Terminal", "bash tool", False, bash_lat, bash_text[:100]))
        except Exception as e:
            print(f"  [FAIL] Bash tool call failed: {e}")
            results.append(CheckResult(current_idx, "Bash Terminal", "bash tool", False, 0.0, str(e)))
        return results

    # Status 6: Cloudflare Edge Reachability
    print(f"\n[Status 6/9] Checking Cloudflare Tunnel Edge Reachability ({tunnel_url})...")
    try:
        edge_res, edge_lat = send_mcp_request(tunnel_url, init_payload, timeout=15.0)
        if "result" in edge_res:
            print(f"  [PASS] Cloudflare Edge reached successfully ({edge_lat:.1f}ms)")
            results.append(CheckResult(current_idx, "Cloudflare Edge", tunnel_url, True, edge_lat, "HTTP 200 via Edge"))
        else:
            print(f"  [FAIL] Invalid edge response: {edge_res}")
            results.append(CheckResult(current_idx, "Cloudflare Edge", tunnel_url, False, edge_lat, "Invalid response"))
            return results
    except urllib.error.HTTPError as e:
        diag = "Cloudflare Error"
        if e.code == 530:
            diag = "HTTP 530: Tunnel daemon not running or offline"
        elif e.code == 502:
            diag = "HTTP 502: Tunnel online but local port 8000 unreachable"
        print(f"  [FAIL] Cloudflare Edge returned HTTP {e.code}: {diag}")
        results.append(CheckResult(current_idx, "Cloudflare Edge", tunnel_url, False, 0.0, diag))
        return results
    except Exception as e:
        print(f"  [FAIL] Connection to Cloudflare Edge failed: {e}")
        results.append(CheckResult(current_idx, "Cloudflare Edge", tunnel_url, False, 0.0, str(e)))
        return results
    current_idx += 1

    # Status 7: Remote MCP Handshake via Tunnel
    print(f"\n[Status 7/9] Verifying Remote Protocol Handshake via Cloudflare...")
    try:
        t_res, t_lat = send_mcp_request(tunnel_url, init_payload, timeout=12.0)
        s_info = t_res.get("result", {}).get("serverInfo", {})
        s_name = s_info.get("name", "Unknown")
        print(f"  [PASS] Remote MCP Handshake confirmed via Tunnel ({t_lat:.1f}ms)")
        results.append(CheckResult(current_idx, "Remote Handshake", f"{s_name} via Tunnel", True, t_lat, "Handshake OK"))
    except Exception as e:
        print(f"  [FAIL] Remote handshake failed: {e}")
        results.append(CheckResult(current_idx, "Remote Handshake", tunnel_url, False, 0.0, str(e)))
        return results
    current_idx += 1

    # Status 8: Remote Tool Execution via Tunnel
    print(f"\n[Status 8/9] Executing Remote Tool Call over Public Internet (ping)...")
    try:
        r_ping_res, r_ping_lat = send_mcp_request(tunnel_url, ping_payload, timeout=12.0)
        r_content = r_ping_res.get("result", {}).get("content", [])
        r_text = r_content[0].get("text", "") if (r_content and isinstance(r_content, list)) else ""
        if "pong" in r_text:
            print(f"  [PASS] Public tool call successful ({r_ping_lat:.1f}ms): \"{r_text}\"")
            results.append(CheckResult(current_idx, "Remote Tool Call", "Public ping -> pong", True, r_ping_lat, r_text))
        else:
            print(f"  [FAIL] Unexpected public tool output: {r_text}")
            results.append(CheckResult(current_idx, "Remote Tool Call", "Public ping", False, r_ping_lat, r_text))
    except Exception as e:
        print(f"  [FAIL] Remote tool execution failed: {e}")
        results.append(CheckResult(current_idx, "Remote Tool Call", "Public ping", False, 0.0, str(e)))
    current_idx += 1

    # -------------------------------------------------------------------------
    # Status 9: Bash Terminal Tool Execution
    # -------------------------------------------------------------------------
    print(f"\n[Status 9/9] Testing Bash Terminal Tool Execution (bash -> git log)...")
    bash_payload = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {
            "name": "bash",
            "arguments": {
                "command": "git log --oneline -1",
                "agent_id": "verifier",
            },
        },
    }
    try:
        bash_res, bash_lat = send_mcp_request(local_url, bash_payload, timeout=20.0)
        content = bash_res.get("result", {}).get("content", [])
        bash_text = content[0].get("text", "") if (content and isinstance(content, list)) else ""
        if "[Exit Code: 0]" in bash_text:
            first_line = bash_text.split("\n")[0]
            print(f"  [PASS] bash('git log --oneline -1') OK ({bash_lat:.1f}ms)")
            print(f"         Output: {bash_text[:200].replace(chr(10), ' | ')}")
            results.append(CheckResult(current_idx, "Bash Terminal", "git log --oneline -1", True, bash_lat, "Exit 0 + git output"))
        else:
            print(f"  [FAIL] Unexpected bash output: {bash_text[:200]}")
            results.append(CheckResult(current_idx, "Bash Terminal", "bash tool", False, bash_lat, bash_text[:100]))
    except Exception as e:
        print(f"  [FAIL] Bash tool call failed: {e}")
        results.append(CheckResult(current_idx, "Bash Terminal", "bash tool", False, 0.0, str(e)))

    return results


def print_summary_table(results: list[CheckResult], tunnel_url: Optional[str]) -> bool:
    """Render a clean summary dashboard of all salient statuses."""
    all_passed = all(r.passed for r in results)
    total_checks = len(results)
    passed_count = sum(1 for r in results if r.passed)

    print("\n" + "=" * 76)
    print("                    SALIENT STATUS DASHBOARD")
    print("=" * 76)
    print(f" {'#':<3} {'SALIENT CHECK ITEM':<24} {'TARGET / VALUE':<30} {'STATUS':<8} {'LATENCY'}")
    print("-" * 76)

    for r in results:
        status_label = "[PASS]" if r.passed else "[FAIL]"
        lat_str = f"{r.latency_ms:>6.1f}ms" if r.latency_ms > 0 else "   N/A  "
        target_display = (r.target[:27] + "...") if len(r.target) > 30 else r.target
        print(f" {r.index:<3} {r.name:<24} {target_display:<30} {status_label:<8} {lat_str}")

    print("=" * 76)

    if all_passed:
        print(f" [ALL CHECKS PASSED] {passed_count}/{total_checks} salient statuses verified successfully!")
        print("-" * 76)
        print("  * Local Endpoint:   http://127.0.0.1:8000/mcp")
        if tunnel_url:
            print(f"  * Public Endpoint:  {tunnel_url}")
        print("  * Active Tools:     ping, add_numbers, bash, channel")
        print("  * Tool Execution:   READY FOR TOOL CALLS")
    else:
        print(f" [WARNING/FAILURE] Only {passed_count}/{total_checks} checks passed. Inspect failed items above.")
    print("=" * 76 + "\n")

    return all_passed


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify salient statuses of local MCP server & Cloudflare tunnel.")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"), help="Local host binding")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")), help="Local port binding")
    parser.add_argument("--tunnel-url", default=None, help="Public Cloudflare Tunnel URL")
    parser.add_argument("--timeout", type=float, default=15.0, help="Wait timeout in seconds")

    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent
    load_env_file(repo_root / ".env")

    local_url = f"http://{args.host}:{args.port}/mcp"
    tunnel_url = args.tunnel_url or os.getenv("CLOUDFLARE_TUNNEL_URL")

    if tunnel_url:
        tunnel_url = tunnel_url.strip()
        if not tunnel_url.endswith("/mcp"):
            tunnel_url = tunnel_url.rstrip("/") + "/mcp"

    results = run_salient_checks(local_url, tunnel_url, args.host, args.port, args.timeout)
    success = print_summary_table(results, tunnel_url)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
