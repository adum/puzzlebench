"""Only the named offline worker tool may act on a solver's behalf."""
import json
import sys


def decision(payload):
    call = payload.get("toolCall", {})
    name, args = call.get("name"), call.get("args")
    if name == "call_mcp_tool" and isinstance(args, dict) and (
            args.get("ServerName") == "puzzlebench" and args.get("ToolName") == "shell"):
        return {"decision": "allow"}
    if name in {"finish", "wait", "wait_5_seconds"}:
        return {"decision": "allow"}
    return {"decision": "deny", "reason": "Use the puzzlebench shell tool in the offline solver workspace."}


if __name__ == "__main__":
    try:
        reply = decision(json.load(sys.stdin))
    except (ValueError, TypeError, AttributeError):
        reply = {"decision": "deny", "reason": "Invalid tool request."}
    print(json.dumps(reply))
