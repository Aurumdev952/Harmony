# 0013. The export renderer image keeps the Playwright base interpreter

Status: applied by the lead on 2026-10-06, pending human ratification (SPEC section 10).

## Context

WP-3b moves every first-party image to one CPython 3.13 interpreter installed from one uv lock, and its test `tests/infra/test_one_interpreter.py` fails any image that installs Python packages outside that lock. WP-1h (merged into `mig/integration` at `efc7abd`) added the export renderer sidecar on `mcr.microsoft.com/playwright/python:v1.63.0-noble`, which ships CPython 3.12 with the matching browser build, and installs its own hash-pinned requirements with pip. The WP-3b reviewer found the two collide on a trial merge: after it, "one interpreter everywhere" is false and the test is red.

Options: (a) rebuild the renderer on `python:3.13-slim` and install Playwright plus Chromium with its system dependencies ourselves, which re-opens the renderer's supply-chain and sandbox review (WP-1h security approved the pinned Microsoft image, its digest, and the hash-pinned requirements); (b) record the renderer as the one image outside the rule, bounded.

## Decision

1. **(b).** The renderer image is the single exception to WP-3b's one-interpreter rule, because it is a sandboxed sidecar with no database or secret access whose browser and interpreter must match the Playwright release. It keeps the digest-pinned Playwright base and its hash-pinned `pip install --require-hashes --no-deps`.
2. **Bounded in code.** `test_one_interpreter.py` checks the interpreter version of every image (not a filename pattern) and allows exactly one exception, named by path, for `docker/renderer/Dockerfile`, with the pip install allowed only when it carries `--require-hashes`. `Dockerfile.test` (the renderer's in-image test image) falls under the same exception. Ruff gets a per-file `target-version = "py312"` for `harmony/worker/renderer/**`.
3. **Revisited by WP-7g** (MapLibre, when the renderer's map origin changes) or earlier if the Playwright Python image publishes a 3.13 build: whichever comes first lifts the exception by moving the renderer to the shared interpreter, with a security re-review.
4. The two items WP-3b deferred "at WP-1h's merge" are due now in WP-3b: the renderer's restart policy outside prod and type-checking `harmony/worker` against Playwright's real types in CI.

## Consequences

- SPEC 1.13: the 3b row reads "one CPython 3.13 interpreter everywhere except the renderer sidecar (decision 0013)".
- WP-3b's PR summary names the exception; WP-7g's definition of done includes lifting it or re-recording why not.
