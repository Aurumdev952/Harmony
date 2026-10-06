"""Serves a production client build where Flask's dev proxy expects webpack.

Outside production, Flask forwards /build/* and /static/* to
webpack-dev-server on localhost:8080 (web/server/routes/webpack_dev_proxy.py).
This server takes that port inside the web container's network namespace and
answers from web/public instead, so the e2e stack runs the real minified
bundles without a dev server.

  /build/<name>   <name> through build/min/sourcemap.json (bundle.css is
                  content-hashed), else build/min/<name>; chunk and font URLs
                  already carry the /build/min/ public path.
  /<path>         web/public/<path>, for the /static/<path> proxy route.
"""

from __future__ import annotations

import json
import mimetypes
import posixpath
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

PUBLIC = Path(sys.argv[1] if len(sys.argv) > 1 else "/public").resolve()
MIN = PUBLIC / "build" / "min"
SOURCEMAP = {
    name: target.removeprefix("/build/min/")
    for name, target in json.loads((MIN / "sourcemap.json").read_text()).items()
}


def resolve(url_path: str) -> Path | None:
    path = posixpath.normpath(unquote(urlsplit(url_path).path)).lstrip("/")
    if path.startswith("build/"):
        name = path.removeprefix("build/").removeprefix("min/")
        candidate = MIN / SOURCEMAP.get(name, name)
    else:
        candidate = PUBLIC / path
    candidate = candidate.resolve()
    if candidate.is_file() and candidate.is_relative_to(PUBLIC):
        return candidate
    return None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        target = resolve(self.path)
        body = target.read_bytes() if target else b"not found\n"
        self.send_response(200 if target else 404)
        content_type = mimetypes.guess_type(target.name)[0] if target else None
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        # The Flask proxy pops this header unconditionally.
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        if len(args) < 2 or str(args[1]) != "200":
            sys.stderr.write(f"e2e-assets {format % args}\n")


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8080), Handler).serve_forever()
