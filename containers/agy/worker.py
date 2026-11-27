"""Minimal stdio MCP server. Started ONLY inside the credential-free offline worker."""
import json
import os
import signal
import subprocess
import sys
import tempfile


TOOL = {
    "name": "shell",
    "description": "Run /bin/sh in /workspace to read /bench, edit solver files, compile and test. No network.",
    "inputSchema": {
        "type": "object", "properties": {
            "command": {"type": "string", "description": "Shell script; heredocs can write files."},
            "timeout": {"type": "integer", "minimum": 1, "maximum": 600,
                        "description": "Seconds to wait (default 120)."},
        }, "required": ["command"], "additionalProperties": False,
    },
}


def shell(args):
    command, timeout = args.get("command"), args.get("timeout", 120)
    if not isinstance(command, str) or not command or type(timeout) is not int or not 1 <= timeout <= 600:
        raise ValueError("Expected a shell command and a timeout of 1 to 600 seconds")
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(["/bin/sh", "-c", command], cwd="/workspace", stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
            status = f"exit {code}"
        except subprocess.TimeoutExpired:
            code, status = 124, f"timed out after {timeout}s"
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        output.seek(0)
        data = output.read(65537)
    text = data[:65536].decode(errors="replace") + ("\n[output truncated]" if len(data) > 65536 else "")
    return {"content": [{"type": "text", "text": f"{status}\n{text}"}], "isError": code != 0}


def respond(request):
    method = request.get("method")
    if "id" not in request:
        return None
    response = {"jsonrpc": "2.0", "id": request["id"]}
    params = request.get("params", {})
    try:
        if method == "initialize":
            version = params.get("protocolVersion")
            supported = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
            result = {"protocolVersion": version if version in supported else supported[-1],
                      "capabilities": {"tools": {}}, "serverInfo": {"name": "puzzlebench", "version": "1"}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [TOOL]}
        elif method == "tools/call" and params.get("name") == "shell":
            result = shell(params.get("arguments", {}))
        else:
            return {**response, "error": {"code": -32601, "message": "Unknown method or tool"}}
        return {**response, "result": result}
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return {**response, "error": {"code": -32602, "message": str(exc)[:250]}}


if __name__ == "__main__":
    while line := sys.stdin.buffer.readline(1024 * 1024 + 1):
        if len(line) > 1024 * 1024:
            break
        try:
            reply = respond(json.loads(line))
        except (ValueError, TypeError, AttributeError):
            break
        if reply is not None:
            print(json.dumps(reply), flush=True)
