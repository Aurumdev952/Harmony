---
name: flask-route-tests-in-process
description: Extra traps for tests/web suites that mount a blueprint and a Potion resource on a bare app (conftest double import, shared Potion classes, AUTHORIZABLE_DIMENSIONS, urlbox recorder)
metadata:
  type: feedback
---

**Rule.** Put shared fakes in a module (`tests/web/<area>/fakes.py`) and import it from both the conftest and the tests. Never import from `conftest` in a test module.

**Why.** There is no `__init__.py` under `tests/`, so pytest loads each conftest as a top-level `conftest` module. A test that imports `tests.web...conftest` gets a second copy with separate globals, and a `monkeypatch.setitem` on that copy does not reach the fixtures. WP-0i lost a debugging round to this.

**How to apply.**

- **Register a subclass of the Potion resource, not the production class.**
  - The pattern: `class Storage(ThumbnailStorageResource): api = None` plus `Meta.name`.
  - Other suites, such as `privilege_escalation`, register the production class on their own `Api`.
  - So a suite can pass on its own and then error with "already registered with a different Api" when the whole `tests/web` tree runs.
  - Always run the whole tree on the py3.8 stack before calling a unit green (see [[py38-web-tests]]).
- **Code that reads `AUTHORIZABLE_DIMENSIONS` needs a deployment config.**
  - This includes `signal_handlers.render_token_query_needs`.
  - Set `app.zen_config = import_configuration_module('harmony_demo')`. Its authorisable dimensions are `StateName` and `source`.
  - A test policy on any other dimension intersects to nothing, and that hides policy leaks.
- **Never call urlbox.**
  - Replace `views.page_renderer.requests` with a recorder.
  - Have the recorder decode the `accessKey` cookie, so tests can assert whose token was minted.
  - If WP-1h replaces urlbox with a sidecar, fake the sidecar call the same way.
- **Patch `get_configuration` in two modules.** Both `views.authentication` and `security.permissions` read it. `authentication_required` calls it even for signed-in users and even with `force_authentication=True`.

Related: [[potion-route-test-harness]], [[flask-web-tests]]
