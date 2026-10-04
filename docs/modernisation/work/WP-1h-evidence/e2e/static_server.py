"""Serves the prebuilt client where dev-mode Flask expects webpack-dev-server.
Flask's proxy pops the Connection header, so always send one."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Connection', 'close')
        super().end_headers()


ThreadingHTTPServer(
    ('127.0.0.1', 8080), partial(Handler, directory='/public')
).serve_forever()
