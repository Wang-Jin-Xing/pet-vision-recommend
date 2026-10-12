"""PetPals 前端一键启动（不依赖 npm / node）。

作用：
1. 托管 frontend/dist 里已构建好的网页（首页、商品、聊天页面）；
2. 把所有 /api 开头的请求转发给后端 http://127.0.0.1:8000。

用法（双击 2_启动网页.bat，或命令行）：
    .venv\\Scripts\\python.exe serve_gui.py
然后浏览器打开 http://127.0.0.1:5199
"""
import http.server
import os
import posixpath
import socketserver
import sys
import urllib.error
import urllib.request
from functools import partial

BACKEND = "http://127.0.0.1:8000"
PORT = 5199
# 本脚本在 backend/ 下，前端的构建产物在它的上一级 frontend/dist
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(_ROOT, "frontend", "dist")


class Handler(http.server.SimpleHTTPRequestHandler):
    """静态文件用父类逻辑；/api 开头转发到后端。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIST, **kwargs)

    def log_message(self, fmt, *args):  # 静音，避免刷屏
        pass

    # ---------- /api 转发 ----------
    def _proxy(self, method: str):
        body = None
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            body = self.rfile.read(length)

        url = BACKEND + self.path
        req = urllib.request.Request(url, data=body, method=method)
        # 透传前端带来的头（含 Authorization），但去掉 Host
        for k, v in self.headers.items():
            if k.lower() in ("host", "content-length"):
                continue
            req.add_header(k, v)

        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = resp.read()
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() in ("transfer-encoding", "content-length",
                                     "connection"):
                        continue
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            data = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type",
                             e.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:  # noqa: BLE001
            msg = f'{{"detail":"后端未启动或不可达: {e}"}}'.encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    def do_GET(self):
        if self.path.startswith("/api"):
            self._proxy("GET")
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api"):
            self._proxy("POST")
        else:
            self.send_error(404)

    def do_PUT(self):
        self._proxy("PUT") if self.path.startswith("/api") else self.send_error(404)

    def do_PATCH(self):
        self._proxy("PATCH") if self.path.startswith("/api") else self.send_error(404)

    def do_DELETE(self):
        self._proxy("DELETE") if self.path.startswith("/api") else self.send_error(404)

    def end_headers(self):
        # 强力禁用缓存：避免浏览器拿到旧的 HTML/JS 导致改动看不到
        self.send_header("Cache-Control",
                         "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    if not os.path.isdir(DIST):
        print(f"找不到前端构建产物：{DIST}")
        print("请确认 frontend/dist 存在。")
        sys.exit(1)
    print("=" * 56)
    print("  PetPals 前端已启动")
    print(f"  浏览器打开： http://127.0.0.1:{PORT}")
    print(f"  后端地址：   {BACKEND}")
    print("=" * 56)
    with ThreadingServer(("127.0.0.1", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止。")


if __name__ == "__main__":
    main()
