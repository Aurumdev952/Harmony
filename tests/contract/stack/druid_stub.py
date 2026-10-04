"""A fixed-answer stand-in for Druid, for the contract stack only.

Harmony reads Druid metadata at import time (config/<code>/database.py) and in
seed migrations, so the stack cannot start without something on the Druid
ports. The web service itself runs with ZEN_OFFLINE=1 and uses its own mock
query client; this stub only has to answer metadata calls deterministically.
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATASOURCE = "harmony_demo_20240101"
MIN_TIME = "2014-01-01T00:00:00.000Z"
MAX_TIME = "2024-01-01T00:00:00.000Z"


def answer_query(query: dict) -> object:
    query_type = query.get("queryType")
    if query_type == "timeBoundary":
        return [
            {
                "timestamp": MIN_TIME,
                "result": {"minTime": MIN_TIME, "maxTime": MAX_TIME},
            }
        ]
    if query_type == "dataSourceMetadata":
        return [{"timestamp": MAX_TIME, "result": {"maxIngestedEventTime": MAX_TIME}}]
    return []


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/")
        if path.endswith("/datasources"):
            self._send([DATASOURCE])
        elif path.endswith("/status/health"):
            self._send(True)
        else:
            self._send({})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            query = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            query = {}
        if not isinstance(query, dict):
            query = {}
        self.log_message("query %s", query.get("queryType"))
        self._send(answer_query(query))

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write(
            f"druid-stub {self.server.server_port} {self.command} {self.path} {format % args}\n"
        )


def main() -> None:
    servers = [
        ThreadingHTTPServer(("0.0.0.0", port), Handler) for port in (8081, 8082, 8888)
    ]
    for server in servers[1:]:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    servers[0].serve_forever()


if __name__ == "__main__":
    main()
