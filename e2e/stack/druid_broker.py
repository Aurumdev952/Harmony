"""A deterministic Druid for the e2e stack.

The contract stack runs the web app with ZEN_OFFLINE=1, whose mock query
client returns unseeded random rows without subtotals or time-format columns,
so the hierarchy, sunburst, number-trend and pie endpoints fail on it and no
chart is the same twice. The e2e stack turns offline mode off and points the
production Druid client at this server instead
(e2e/stack/compose.e2e.yaml). It answers:

- the coordinator calls DruidMetadata_ makes (datasource list, version, load
  status) for one datasource;
- timeBoundary and dataSourceMetadata with a fixed 2014-2024 range;
- groupBy and timeseries through tests/golden/synth.py, which shapes rows the
  way Druid 0.23 does from a fixed table of harmony_demo locations, so the
  same query always gets the same bytes.

Anything synth cannot answer comes back as a Druid-style 500 with the reason,
which reaches the browser as a 5xx and fails the test that caused it. It runs
in the web image (Python 3.8) with the repository on PYTHONPATH.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Loaded by path: in the web image, flask-potion installs a top-level `tests`
# package that shadows the repository's.
_SYNTH_PATH = Path(__file__).resolve().parents[2] / "tests" / "golden" / "synth.py"
_spec = importlib.util.spec_from_file_location("golden_synth", _SYNTH_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot load {_SYNTH_PATH}")
synth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(synth)

DATASOURCE = "harmony_demo_20240101"
VERSION = "2024-01-01T00:00:00.000Z"
MIN_TIME = "2014-01-01T00:00:00.000Z"
MAX_TIME = "2024-01-01T00:00:00.000Z"
# Seeds every synthetic answer, with the query's structure.
SEED_NAME = "e2e"
# The second indicator e2e/stack/seed.sql adds to the Data Catalog, and no
# bucket left empty by chance, so every chart in the suite has data to draw.
SYNTH_OPTIONS = {"extra_fields": ["e2e_yellow_fever_deaths"], "dense": True}

COORDINATOR = "/druid/coordinator/v1"


def _metric_names(query: Dict[str, Any]) -> List[str]:
    names = [
        a.get("name") or a["aggregator"]["name"] for a in query.get("aggregations", [])
    ]
    return names + [p["name"] for p in query.get("postAggregations", [])]


def _dimension_names(query: Dict[str, Any]) -> List[str]:
    return [
        d if isinstance(d, str) else d["outputName"]
        for d in query.get("dimensions", [])
    ]


def _as_events(query: Dict[str, Any], rows: List[list]) -> List[Dict[str, Any]]:
    """Array rows to the groupBy v1 shape, for callers that do not ask for
    resultAsArray (the dimension value lookups)."""
    by_time = query["granularity"] != "all"
    names = _dimension_names(query) + _metric_names(query)
    start = query["intervals"][0].split("/")[0]
    events = []
    for row in rows:
        values = row[1:] if by_time else row
        stamp = row[0] if by_time else start
        if isinstance(stamp, int):
            stamp = _iso_from_ms(stamp)
        events.append(
            {"version": "v1", "timestamp": stamp, "event": dict(zip(names, values))}
        )
    return events


def _iso_from_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


def answer_query(query: Dict[str, Any]) -> object:
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
    if isinstance(query.get("intervals"), str):
        # Druid takes one interval as a bare string; synth expects a list.
        query = {**query, "intervals": [query["intervals"]]}
    if query_type == "groupBy" and not query.get("context", {}).get("resultAsArray"):
        as_array = copy.deepcopy(query)
        as_array.setdefault("context", {})["resultAsArray"] = True
        return _as_events(query, synth.synthesize(SEED_NAME, as_array, SYNTH_OPTIONS))
    return synth.synthesize(SEED_NAME, query, SYNTH_OPTIONS)


def answer_get(path: str) -> Tuple[int, object]:
    if path == f"{COORDINATOR}/metadata/datasources":
        return 200, [DATASOURCE]
    if path == f"{COORDINATOR}/metadata/datasources/{DATASOURCE}":
        return 200, {"segments": [{"version": VERSION}]}
    if path == f"{COORDINATOR}/loadstatus":
        return 200, {DATASOURCE: 100}
    if path.endswith("/status/health"):
        return 200, True
    return 404, {"error": f"e2e druid has no GET {path}"}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._send(*answer_get(self.path.split("?", 1)[0].rstrip("/")))

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        query = json.loads(self.rfile.read(length) or b"{}")
        try:
            self._send(200, answer_query(query))
        except (NotImplementedError, ValueError, KeyError) as error:
            self.log_message("cannot answer %s: %r", query.get("queryType"), error)
            self._send(
                500,
                {"error": "Unknown exception", "errorMessage": f"e2e druid: {error!r}"},
            )

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        sys.stderr.write(f"e2e-druid {self.command} {self.path} {format % args}\n")


def main() -> None:
    # All interfaces of the container, which sits on the stack's internal
    # network only; nothing publishes these ports.
    servers = [
        ThreadingHTTPServer(("0.0.0.0", port), Handler)  # noqa: S104
        for port in (8081, 8082, 8888)
    ]
    for server in servers[1:]:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    servers[0].serve_forever()


if __name__ == "__main__":
    main()
