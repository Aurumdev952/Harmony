---
name: druid-response-streaming
description: Druid query responses must be parsed incrementally; a whole-body JSON decode (msgspec/orjson/json.loads) was rejected in review for resource exhaustion
metadata:
  type: feedback
---

Parse streamed Druid responses row by row; never decode the whole body at once. `db/druid/json_stream.iter_json_array` (stdlib C scanner over a rolling UTF-8 buffer) is the parser since WP-3b `ab662b4`.

**Why:** WP-3b first used msgspec (fastest, exact longs); a security review flagged that a 200 MB body peaked at 903 MB (vs <1 MB for the old yajl stream) and decoded rows lived until export_pandas finished. The lead required streaming or a byte cap; streaming kept memory at ~10 MB with near-yajl speed and no new dependency.

**How to apply:** when touching `db/druid/query_client.py` or the FastAPI Druid client (C-9), keep an iterator-returning parser, keep Long.MIN_VALUE exact, reject bare NaN/Infinity, and run `tests/druid/test_druid_response_parsing.py` (memory and speed guards). Measure peak RSS, not just speed, for any parser change. Host timing is unreliable under load: compare against a stdlib `json.loads` run in the same window.
