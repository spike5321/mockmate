"""
Mock 工具网关 - HTTP 服务器

启动方式:
  python3 mock_tool_server.py --host 0.0.0.0 --port 18090

调用方式:
  POST /tools/{scenario_id}/{tool_name}.{function_name}
  Body: {"key1": "value1", ...}

例如:
  curl -X POST http://127.0.0.1:18090/tools/backend_intern/mock_question_bank.pick \
    -H 'Content-Type: application/json' \
    -d '{"track": "coding", "difficulty": "medium", "focus": ["链表"]}'
"""

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

from mock_tools import call_tool


class ToolGatewayHandler(BaseHTTPRequestHandler):
    """处理 /tools/{scenario_id}/{tool}.{function} 路由。"""

    def do_GET(self):
        if self.path in ("/health", "/healthz"):
            self._json_response(200, {"ok": True, "service": "mockmate-tool-gateway"})
        elif self.path == "/scenarios":
            self._json_response(200, {"ok": True, "scenarios": self._list_scenarios()})
        else:
            self._json_response(404, {"error": "not found", "hint": "use POST /tools/{scenario_id}/{tool}.{function}"})

    def do_POST(self):
        path = urlparse(self.path).path
        # 期望: /tools/{scenario_id}/{tool}.{function}
        parts = path.strip("/").split("/")
        if len(parts) != 3 or parts[0] != "tools":
            self._json_response(400, {"error": "bad path", "expected": "/tools/{scenario_id}/{tool}.{function}"})
            return

        _, scenario_id, tool_func = parts
        if "." not in tool_func:
            self._json_response(400, {"error": "bad tool_func", "expected": "{tool}.{function}"})
            return

        tool_name, function_name = tool_func.split(".", 1)

        # 读 body
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            args = json.loads(raw) if raw else {}
        except (ValueError, json.JSONDecodeError) as e:
            self._json_response(400, {"error": f"bad json: {e}"})
            return

        # 调用
        result = call_tool(scenario_id, tool_name, function_name, args)
        self._json_response(200, result)

    def log_message(self, format, *args):
        # 简化日志输出
        sys.stderr.write("[mock_tool_server] " + (format % args) + "\n")

    def _json_response(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _list_scenarios() -> list:
        """列出已加载的场景 ID。"""
        from pathlib import Path

        scenarios_dir = Path(__file__).resolve().parent.parent / "scenarios"
        return [p.stem for p in scenarios_dir.glob("*.json") if not p.stem.endswith(".report")]


def main():
    parser = argparse.ArgumentParser(description="MockMate 工具网关")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=18090, help="监听端口")
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), ToolGatewayHandler)
    print(f"[mock_tool_server] listening on http://{args.host}:{args.port}")
    print(f"[mock_tool_server] try: curl http://127.0.0.1:{args.port}/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[mock_tool_server] shutting down")
        server.server_close()


if __name__ == "__main__":
    main()
