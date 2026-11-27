"""Loopback-only Gemini response fixture; never contacts Google or uses a real key."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        tools = [tool["name"] for group in request.get("tools", [])
                 for tool in group.get("functionDeclarations", group.get("function_declarations", []))]
        shell = "call_mcp_tool" if "call_mcp_tool" in tools else None
        prior = [part for msg in request.get("contents", []) for part in msg.get("parts", [])
                 if "functionResponse" in part or "function_response" in part]
        print("worker tool:", shell, "prior responses:", len(prior), flush=True)
        if shell and not prior:
            part = {"functionCall": {"name": shell, "args": {"ServerName": "puzzlebench", "ToolName": "shell",
                    "Arguments": {"command": "printf tested > fixture-marker"}}}}
        else:
            part = {"text": "Fixture finished."}
        data = {"candidates": [{"content": {"role": "model", "parts": [part]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 3, "totalTokenCount": 13}}
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(("data: " + json.dumps(data) + "\n\n").encode())


HTTPServer(("127.0.0.1", 8766), Handler).serve_forever()
