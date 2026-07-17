import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 -- 屏蔽测试服务器访问日志
        pass

    def do_GET(self):
        if self.path == "/ok":
            body = b"<html><head><title>OK</title></head><body>hello</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/redirect-once":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
        elif self.path == "/redirect-loop":
            self.send_response(302)
            self.send_header("Location", "/redirect-loop")
            self.end_headers()
        elif self.path.startswith("/redirect-chain/"):
            remaining = int(self.path.rsplit("/", 1)[1])
            self.send_response(302)
            if remaining <= 0:
                self.send_header("Location", "/ok")
            else:
                self.send_header("Location", f"/redirect-chain/{remaining - 1}")
            self.end_headers()
        elif self.path == "/forbidden":
            self.send_response(403)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture
def local_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield f"http://{host}:{port}"
    server.shutdown()
    thread.join(timeout=5)
