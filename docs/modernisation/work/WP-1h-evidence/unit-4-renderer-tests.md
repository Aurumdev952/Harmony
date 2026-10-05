# WP-1h unit 4: renderer sidecar tests

Date: 2026-10-04. Image built from `infra-request/Dockerfile` (base `mcr.microsoft.com/playwright/python:v1.63.0-noble@sha256:72bd171a…40da1f0`, driver 1.63.0 per `/ms-playwright/.docker-info`), with a throwaway layer adding `pytest==8.3.5` and `ENTRYPOINT ["python", "-m", "pytest", "-p", "no:cacheprovider"]`.

## Inside the image, no network (`--network none`)

```
docker run --rm --network none -v <worktree>:/src:ro harmony-renderer-test:wp1h tests/worker/renderer -q
88 passed in 24.78s
```

The browser tests run against two local origins in the container: the dashboard origin, and a second origin the page tries to reach. Results:

```
test_png_is_rendered_signed_in_after_the_ready_signal PASSED
test_pdf_and_jpeg_are_rendered PASSED
test_full_page_capture_is_clipped_at_the_height_limit PASSED
test_every_other_destination_is_blocked_and_recorded PASSED
test_a_refused_token_redirect_to_login_fails_the_render PASSED
test_a_page_error_fails_the_render PASSED
test_a_page_that_never_signals_ready_times_out_on_the_deadline PASSED
test_output_over_the_size_limit_is_refused PASSED
test_nothing_from_one_render_survives_into_the_next PASSED
9 passed in 14.67s
```

- Egress: the page asks for `tiles.invalid`, `fonts.invalid`, `collect.invalid` and the second local origin. The route guard aborts all four and records them. The second origin logs no request.
- Isolation: the first render writes `localStorage`. The second render, with a different token, reads `none` and sends only its own cookie.

## On the host (Python 3.9 uv env, no Playwright)

```
uv run pytest tests/worker tests/web -q -p no:cacheprovider -W ignore
1 failed, 275 passed, 1 skipped
```

The skip is `test_render_browser.py`, which needs Playwright. The one failure is the existing `flask_migrate` import in `tests/web/test_graphql_endpoint_removed.py`.

## Static checks

- `black==22.6.0 --skip-string-normalization --check`: clean.
- `ruff check --isolated --select F,E9,B,UP,I --target-version py39`: clean.
- `mypy --python-version 3.12` with playwright 1.63.0 installed: no issues in 7 files.
