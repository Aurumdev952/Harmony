"""A stand-in for Harmony's renderer service (harmony/worker/renderer).

Harmony posts `{url, format, token, ...}` to the renderer's `POST /render`, and
the renderer opens the dashboard URL in Chromium with the token as the
`accessKey` cookie and answers with the file
(web/server/routes/views/page_renderer.py). The e2e stack points RENDERER_URL
here. This server does the part a test can check without a browser: it loads
the URL with that cookie from inside the stack and refuses unless the page
answers 200 rather than redirecting to sign-in. Then it returns a fixed
one-page PDF or a 1x1 JPEG. It renders nothing, and it does not do thumbnails
(png): those fail with an error code, as a real renderer failure would.

  POST /render   {"url": "http://web:5000/...", "format": "pdf"|"jpeg", "token": ...}
                 -> 200 with the file, else {"error": "<code>"} like the renderer
"""

from __future__ import annotations

import base64
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

# RENDER_WEB_ORIGIN in the web app: the only origin this stand-in loads.
WEB = "web:5000"

PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)
# A white 1x1 JPEG (Pillow, quality 50).
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABALDA4MChAODQ4SERATGCgaGBYWGDEjJR0oOjM9PDkzODdA"
    "SFxOQERXRTc4UG1RV19iZ2hnPk1xeXBkeFxlZ2P/2wBDARESEhgVGC8aGi9jQjhCY2NjY2NjY2NjY2Nj"
    "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2P/wAARCAABAAEDASIAAhEBAxEB/8QA"
    "HwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIh"
    "MUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVW"
    "V1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXG"
    "x8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQF"
    "BgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAV"
    "YnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
    "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq"
    "8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD0CiiigD//2Q=="
)
BODIES = {"pdf": (PDF, "application/pdf"), "jpeg": (JPEG, "image/jpeg")}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


def load_as_user(url: str, token: str) -> int:
    parts = urlsplit(url)
    if (parts.scheme, parts.netloc) != ("http", WEB):
        return 0
    inside = urlunsplit(("http", WEB, parts.path, parts.query, ""))
    # The scheme and host are checked above; only the path comes from the caller.
    request = Request(inside, headers={"Cookie": f"accessKey={token}"})  # noqa: S310
    try:
        with build_opener(_NoRedirect).open(request, timeout=30) as response:
            return response.status
    except HTTPError as error:
        return error.code


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, code: str) -> None:
        self._send(status, json.dumps({"error": code}).encode(), "application/json")

    def do_POST(self) -> None:
        if self.path != "/render":
            self._error(404, "not_found")
            return
        length = int(self.headers.get("Content-Length", "0"))
        spec = json.loads(self.rfile.read(length) or b"{}")
        output_format = spec.get("format")
        if output_format not in BODIES or not spec.get("url") or not spec.get("token"):
            self._error(400, "unsupported_request")
            return
        status = load_as_user(spec["url"], spec["token"])
        if status != 200:
            sys.stderr.write(f"e2e-renderer: dashboard answered HTTP {status}\n")
            self._error(502, "page_refused")
            return
        self._send(200, *BODIES[output_format])

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        # The body carries the render token; log the path only.
        sys.stderr.write(f"e2e-renderer {self.command} {self.path} {code}\n")


if __name__ == "__main__":
    # All interfaces of the container, which sits on the stack's internal
    # network only; nothing publishes this port. 8080 is RENDERER_URL's default.
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()  # noqa: S104
