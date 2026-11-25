"""Claude Code -> Jarvis: tells Jarvis when Claude Code is waiting for you (a permission prompt, or it's idle and
needs input), so he can say it out loud and ping your phone.

Claude Code runs this from a "Notification" hook and passes the details as JSON on stdin. It quietly does nothing
if Jarvis isn't running. Set it up by adding this to your Claude Code settings (~/.claude/settings.json), with
your own path to Jarvis:

  "hooks": {"Notification": [{"hooks": [{"type": "command",
      "command": "python \"C:/path/to/JARVIS/tools/claude_code_notify.py\""}]}]}
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    try:  # read as UTF-8 bytes: Windows' default console encoding would garble non-English folder names
        event = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except Exception:
        event = {}
    try:
        key = (ROOT / "data" / "access_key.txt").read_text().strip()
        port = os.getenv("JARVIS_PORT", "8765")
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines() if (ROOT / ".env").exists() else []:
            if line.strip().startswith("JARVIS_PORT=") and line.split("=", 1)[1].strip():
                port = line.split("=", 1)[1].strip()
        body = json.dumps({"message": event.get("message", ""), "cwd": event.get("cwd", "")}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/claude-code?key={key}", body,
                                     {"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        pass  # Jarvis isn't running: nothing to do
    return 0


if __name__ == "__main__":
    sys.exit(main())
