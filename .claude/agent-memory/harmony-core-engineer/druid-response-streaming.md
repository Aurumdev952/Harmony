---
name: druid-response-streaming
description: Druid query responses must be parsed incrementally; a whole-body JSON decode (msgspec/orjson/json.loads) was rejected in review for resource exhaustion
metadata:
  type: feedback
---

Parse streamed Druid responses row by row; never decode the whole body at once. `db/druid/json_stream.iter_json_array` (stdlib C scanner over a rolling UTF-8 buffer) is the parser since WP-3b `ab662b4`.

**Why:** WP-3b first used msgspec (fastest, exact longs); a security review flagged that a 200 MB body peaked at 903 MB (vs <1 MB for the old yajl stream) and decoded rows lived until export_pandas finished. The lead required streaming or a byte cap; streaming kept memory at ~10 MB with near-yajl speed and no new dependency.

Two traps found in review (2026-10-06, `a3d5a3c`): `raw_decode` silently returns a short number when a read splits "0.5" after the "." (refill on a `.`/`e`/`E` tail at buffer end); and any decode error refills until EOF, so one malformed or padded element buffers the rest of the body (fixed with `_MAX_ELEMENT_CHARS`). The cap's memory cost depends on the widest character: about 5 bytes per cap character for ASCII, but about 14 once one astral character makes the buffer UCS-4. So the cap is 16 Mi characters (224 MiB worst case, follow-up `58974e71`). A UTF-8 byte cap does not bound that, and its test scales a traced 1/16-scale peak to the real cap. Boundary tests must put numbers at the *top level*, not only inside rows. The speed guard is a ratio to `json.loads`, because absolute bounds flaked at load 45 or more.

**How to apply:** when touching `db/druid/query_client.py` or the FastAPI Druid client (C-9), keep an iterator-returning parser, keep Long.MIN_VALUE exact, reject bare NaN/Infinity, and run `tests/druid/test_druid_response_parsing.py` (memory and speed guards). Measure peak RSS, not just speed, for any parser change. Host timing is unreliable under load: compare against a stdlib `json.loads` run in the same window.
