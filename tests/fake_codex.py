"""Stand-in for the codex CLI, so gen.py can be tested without spending renders.

Behaves like `codex exec --json`: prints a thread.started event, drops a PNG into
$CODEX_HOME/generated_images/<thread_id>/, then prints an agent message. Knobs:

  FAKE_CODEX_LOG       append each call's argv and cwd here as JSON lines
  FAKE_CODEX_SLEEP     seconds to "render" for
  FAKE_CODEX_NO_IMAGE  set to finish without producing an image
  FAKE_CODEX_RUNNING   directory used to record how many renders overlap
  FAKE_CODEX_LOGGED_OUT  set to make `codex login status` fail
"""

import json
import os
import struct
import sys
import time
import uuid
import zlib
from pathlib import Path


def png(width, height):
    raw = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def main():
    args = sys.argv[1:]
    if args[:1] == ["--version"]:
        print("codex-cli 0.0.0-fake")
        return 0
    if args[:2] == ["login", "status"]:
        if os.environ.get("FAKE_CODEX_LOGGED_OUT"):
            print("Not logged in")
            return 1
        print("Logged in using ChatGPT")
        return 0

    log = os.environ.get("FAKE_CODEX_LOG")
    if log:
        with open(log, "a") as f:
            f.write(json.dumps({"argv": args, "cwd": os.getcwd()}) + "\n")

    thread_id = str(uuid.uuid4())
    print(json.dumps({"type": "thread.started", "thread_id": thread_id}), flush=True)

    running = os.environ.get("FAKE_CODEX_RUNNING")
    marker = None
    if running:
        marker = Path(running) / thread_id
        marker.touch()
        overlap = len(list(Path(running).iterdir()))
        with open(Path(running).with_suffix(".peaks"), "a") as f:
            f.write(f"{overlap}\n")

    time.sleep(float(os.environ.get("FAKE_CODEX_SLEEP", "0")))

    if not os.environ.get("FAKE_CODEX_NO_IMAGE"):
        home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        out = home / "generated_images" / thread_id
        out.mkdir(parents=True, exist_ok=True)
        (out / f"ig_{uuid.uuid4().hex[:12]}.png").write_bytes(png(64, 48))

    if marker:
        marker.unlink()
    message = "I can't make that." if os.environ.get("FAKE_CODEX_NO_IMAGE") else "DONE"
    print(json.dumps({"type": "item.completed",
                      "item": {"type": "agent_message", "text": message}}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
