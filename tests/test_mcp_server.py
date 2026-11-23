import json, os, time, unittest, urllib.request
def parse_body(r):
    s = r.strip()
    try: return json.loads(s)
    except Exception:
        for l in reversed(s.splitlines()):
            if l.startswith("data:"): return json.loads(l[5:].strip())
        raise
class Rpc:
    def __init__(self, u, aid=None): self.u, self.aid, self.sid, self.n = u, aid, None, 600
    def call(self, m, p=None):
        self.n += 1
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.sid: h["mcp-session-id"] = self.sid
        if self.aid: h["X-Agent-ID"] = self.aid
        d = json.dumps({"jsonrpc": "2.0", "id": self.n, "method": m, "params": p or {}}).encode()
        with urllib.request.urlopen(urllib.request.Request(self.u, data=d, headers=h, method="POST"), timeout=15) as resp:
            self.sid = resp.headers.get("mcp-session-id") or self.sid
            return parse_body(resp.read().decode("utf-8", "replace"))
class TestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = Rpc(os.environ.get("MCP_LOCAL_URL", "http://127.0.0.1:8000/mcp"), "suite")
        res = cls.r.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    def test_tools(self):
        names = {t["name"] for t in self.r.call("tools/list")["result"]["tools"]}
        self.assertTrue({"ping", "add_numbers", "bash", "channel"}.issubset(names))
        self.assertIn("pong", json.dumps(self.r.call("tools/call", {"name": "ping", "arguments": {"agent_id": "suite"}})).lower())
        self.assertIn("42", json.dumps(self.r.call("tools/call", {"name": "add_numbers", "arguments": {"a": 12.5, "b": 29.5, "agent_id": "suite"}})))
    def test_channels(self):
        cid = f"ch-{int(time.time())}-{os.getpid()}"
        self.assertIn("CHANNEL_NOT_FOUND", json.dumps(self.r.call("tools/call", {"name": "channel", "arguments": {"action": "read", "channel_id": cid, "user_id": "u2"}})))
        self.r.call("tools/call", {"name": "channel", "arguments": {"action": "create", "channel_id": cid, "user_id": "u1"}})
        self.assertIn("NOT_SUBSCRIBED", json.dumps(self.r.call("tools/call", {"name": "channel", "arguments": {"action": "write", "channel_id": cid, "user_id": "u1", "message": "x"}})))
        for u in ("u1", "u2"): self.r.call("tools/call", {"name": "channel", "arguments": {"action": "subscribe", "channel_id": cid, "user_id": u, "subscribed": True}})
        msg = f"m-{int(time.time())}"
        self.r.call("tools/call", {"name": "channel", "arguments": {"action": "write", "channel_id": cid, "user_id": "u1", "message": msg}})
        self.assertIn(msg, json.dumps(self.r.call("tools/call", {"name": "ping", "arguments": {"agent_id": "u2"}})))
if __name__ == "__main__": unittest.main(verbosity=2)
