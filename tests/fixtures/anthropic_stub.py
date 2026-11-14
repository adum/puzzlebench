"""Local Messages API fixture for exercising Claude CLI without model requests."""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.startswith("/v1/messages/count_tokens"):
            self.reply({"input_tokens": 50})
            return
        if not self.path.startswith("/v1/messages"):
            self.reply({})
            return
        with Path('/workspace/fixture-requests.jsonl').open('a') as log:
            log.write(json.dumps({key: request.get(key) for key in ('model', 'max_tokens', 'output_config', 'thinking')}) + '\n')
        tool_results = [block for message in request.get("messages", [])
                        for block in (message.get("content", []) if isinstance(message.get("content"), list) else [])
                        if block.get("type") == "tool_result"]
        if not tool_results:
            command = (
                "python3 -c \"import os; "
                "assert not os.environ.get('ANTHROPIC_API_KEY'); "
                "assert not os.environ.get('CLAUDE_CODE_OAUTH_TOKEN'); "
                "open('/workspace/claude-scrub-ok', 'w').write('scrubbed'); "
                "print('scrubbed')\""
            )
            content = {"type": "tool_use", "id": "toolu_fixture", "name": "Bash",
                       "input": {"command": command, "description": "Verify subprocess credential scrubbing"}}
            stop = "tool_use"
        else:
            content = {"type": "text", "text": "Sandbox fixture completed."}
            stop = "end_turn"
        message = {"id": "msg_fixture", "type": "message", "role": "assistant",
                   "model": request["model"], "content": [content], "stop_reason": stop,
                   "stop_sequence": None, "usage": {"input_tokens": 50, "output_tokens": 10}}
        if not request.get("stream"):
            self.reply(message)
            return
        events = [{"type": "message_start", "message": {**message, "content": [], "stop_reason": None}}]
        if content["type"] == "tool_use":
            events += [
                {"type": "content_block_start", "index": 0, "content_block": {**content, "input": {}}},
                {"type": "content_block_delta", "index": 0,
                 "delta": {"type": "input_json_delta", "partial_json": json.dumps(content["input"])}},
            ]
        else:
            events += [
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "index": 0,
                 "delta": {"type": "text_delta", "text": content["text"]}},
            ]
        events += [
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 10}},
            {"type": "message_stop"},
        ]
        data = "".join(f"event: {item['type']}\ndata: {json.dumps(item)}\n\n" for item in events).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.reply({})

    def reply(self, value):
        data = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 0), Handler)
    Path("/workspace/fixture-ready.json").write_text(json.dumps({"port": server.server_port, "pid": os.getpid()}))
    server.serve_forever()
