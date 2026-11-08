"""最小契约探针：只提供 /health 和 /ping。"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 0


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send({"ok": True, "pid": os.getpid(), "port": PORT})
        elif self.path.startswith("/ping"):
            self._send({"ok": True, "pong": True, "pid": os.getpid(), "port": PORT})
        else:
            self._send({"ok": False, "error": "not found"}, 404)

    def log_message(self, *args):
        pass


def main() -> None:
    global PORT
    port = 0
    for i, arg in enumerate(sys.argv):
        if arg == "--port" and i + 1 < len(sys.argv):
            try:
                port = int(sys.argv[i + 1])
            except ValueError:
                port = 0
    port = port or int(os.environ.get("BAB_MODULE_PORT") or 40739)
    PORT = port
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
