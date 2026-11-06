# -*- coding: utf-8 -*-
"""__NAME__：最小的模组骨架（只用标准库，不装任何依赖）。"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

NAME = "__NAME__"
VERSION = "0.1.0"

# Windows 下把控制台按 UTF-8 输出：模组名里有中文时，默认代码页会直接抛 UnicodeEncodeError。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


class Handler(BaseHTTPRequestHandler):
    # HTTP 头只能是 latin-1，所以这一行别放中文（模组名常常是中文）
    server_version = "BAB-module/" + VERSION

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path == "/health":
            self._send(200, {"ok": True, "name": NAME, "version": VERSION})
            return
        if url.path == "/ping":
            word = (parse_qs(url.query).get("word") or [""])[0]
            self._send(200, {"ok": True, "pong": "在" if not word else f"在（{word}）"})
            return
        self._send(404, {"ok": False, "error": f"没有这个接口：{url.path}"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            args = json.loads(raw.decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001
            args = {}
        self.do_GET() if self.path.startswith("/ping") else self._send(
            200, {"ok": True, "echo": args})

    def log_message(self, fmt: str, *args) -> None:  # 别把日志打到 stderr
        try:
            sys.stderr.write("[%s] %s\n" % (NAME, fmt % args))
        except Exception:  # noqa: BLE001
            pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    port = 0
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])
    if not port:
        print("用法：python server.py --port <端口>（外壳会用 BAB_MODULE_PORT 告诉你）")
        return 2
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"{NAME} {VERSION} listening on 127.0.0.1:{port}", flush=True)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
