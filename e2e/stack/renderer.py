"""A stand-in for Urlbox, the service that renders dashboard PDFs and images.

Harmony asks Urlbox to load the dashboard as the requesting user (an
`accessKey` JWT cookie it mints for the purpose) and return the rendered
file (web/server/routes/views/page_renderer.py). The e2e stack points
URLBOX_API_URL here. This server does the part a test can check without a
browser: it loads the dashboard URL with that cookie from inside the stack and
refuses unless the page answers 200 and does not redirect to sign-in. Then it
returns a fixed one-page PDF or a 1x1 JPEG. Thumbnails (png) are not
served: the stack seeds them (tests/contract/stack/seed_cache.py). It does not render anything.

  GET /v1/<api key>/<pdf|jpg>?url=...&cookie=accessKey=...
"""

from __future__ import annotations

import base64
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

# Harmony builds the dashboard URL from the browser's Host header (the
# loopback forward); inside the stack the web service answers on web:5000.
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
BODIES = {"pdf": (PDF, "application/pdf"), "jpg": (JPEG, "image/jpeg")}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


def load_as_user(url: str, cookie: str) -> int:
    parts = urlsplit(url)
    inside = urlunsplit(("http", WEB, parts.path, parts.query, ""))
    # The scheme and host are fixed above; only the path comes from the caller.
    request = Request(inside, headers={"Cookie": cookie})  # noqa: S310
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

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        output_format = parts.path.rstrip("/").rsplit("/", 1)[-1]
        params = {k: v[0] for k, v in parse_qs(parts.query).items()}
        if output_format not in BODIES or "url" not in params:
            self._send(
                400, b"e2e renderer: need /v1/<key>/<pdf|jpg>?url=", "text/plain"
            )
            return
        status = load_as_user(params["url"], params.get("cookie", ""))
        if status != 200:
            message = (
                f"e2e renderer: dashboard answered HTTP {status} to the minted cookie"
            )
            self._send(502, message.encode(), "text/plain")
            return
        self._send(200, *BODIES[output_format])

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        # The query string carries the minted session cookie; log the path only.
        sys.stderr.write(
            f"e2e-renderer {self.command} {urlsplit(self.path).path} {code}\n"
        )


if __name__ == "__main__":
    # All interfaces of the container, which sits on the stack's internal
    # network only; nothing publishes this port.
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()  # noqa: S104
