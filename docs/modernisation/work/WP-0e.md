---
wp: "0e"
title: "Delete dead frontend code and dependencies"
status: blocked
owner_role: "frontend-platform"
instances:
  - name: "frontend-platform-1"
    files:
      - package.json
      - yarn.lock
      - web/public/js/vendor/**
      - web/client/entryPoints/navbarEntry.js
      - docs/modernisation/work/WP-0e.md
branch: "mig/WP-0e-dead-frontend-code"
requirements: []
contracts_consumed: []
contracts_changed: []
security_review: false
---

# WP-0e: Delete dead frontend code and dependencies

## Plan

Units, in order. Each line names the change and the check that ends it. Units 3 to 6 touch Jinja templates (`web/server/templates/**`, owner backend) and SCSS (`web/public/scss/**`, owner frontend-design); those edits are requests R1 to R5 below, and the vendor-file deletions this role owns wait for them so no commit leaves a template pointing at a missing script.

1. Remove `papaparse`, `simple-statistics`, `d3-random` and `d3-scale-chromatic` from `package.json`, regenerate `yarn.lock` with yarn, and delete their orphaned flow-typed stubs under `web/public/js/vendor/flow-typed/npm/`. Check: no import of any of the four anywhere; `yarn install --frozen-lockfile`; `yarn build` on host Node 24 and inside `docker/web/Dockerfile_web-client` (node:18.17, the shipped image); Flow error set unchanged against `main`; built JS and CSS byte-identical to `main`.
2. Drop the stale `templates/query.html` reference from the comment in `web/client/entryPoints/navbarEntry.js`. Check: eslint on the file; bundles byte-identical to `main` (comments are stripped).
3. Delete `web/server/templates/query.html` and `web/server/templates/facilities_map.html` (R1). Check: no `render_helper`/`render_template` call or include names either template; `navbar.bundle.js` stays because `data_status.html` loads it.
4. Remove the `asyncMapChunk.bundle.js` script from `grid_dashboard.html` (R2). Check: webpack emits no `asyncMapChunk` chunk (no `webpackChunkName` anywhere in `web/client`), so today the tag 404s on every screenshot request.
5. Remove `bootstrap-5.2.0.js` from `layout.html` (R3), then delete `web/public/js/vendor/bootstrap-5.2.0.js` and `web/public/js/vendor/min/bootstrap-5.2.0.js` (this role, after R3). Check: no `data-bs-*` attribute, `window.bootstrap` or `$.fn` bootstrap plugin call in `web/client` or the templates that extend `layout.html` (`data_catalog_changes.html` loads its own Bootstrap 4 from a CDN and does not extend `layout.html`); `yarn build`; page check.
6. Remove `bootstrap-datepicker-1.5.1.js` and `bootstrap-select-1.12.2.patched.js` from `query_app_vendor_scripts.html` (R4) and their SCSS (R5), then delete both scripts from `web/public/js/vendor/` and `web/public/js/vendor/min/` (this role, after R4). Check: no `.selectpicker`, `.datepicker(`, `.input-daterange`, `.input-append`, `.bs-searchbox` usage in `web/client` or templates (the React `DatePicker` does not use them); `yarn build`; page check.
7. Page check across the stack: all 15 page routes render with no console errors (`verify`), once R1 to R5 have landed in this stack.

Out of scope, noted for the lead: `web/client/entryPoints/newUserButtonEntry.js` is built as an entry but no template loads `newUserButton.bundle.js`. It looks dead; it is not on the phase 0e list, so it is left alone here.

## Contract changes

None.

## Requests

- [x] backend: R1. Delete `web/server/templates/query.html` and `web/server/templates/facilities_map.html`. No route renders either (`grep -rn "query.html\|facilities_map" web/server` finds only the files themselves). (blocks unit 3) Done on `mig/WP-0e-dead-frontend-code-backend` (backend-3).
- [x] backend: R2. In `web/server/templates/grid_dashboard.html`, delete the block that loads the map chunk on screenshot requests, i.e. the `{#- NOTE: When a screenshot request ... #}` comment and the `{% if is_screenshot_request %} <script src="{{ bundle_resource_url('asyncMapChunk.bundle.js') }}"></script> {% endif %}` block. Webpack emits no such chunk, so the tag only 404s. (blocks unit 4) Done on `mig/WP-0e-dead-frontend-code-backend` (backend-3).
- [x] backend: R3. In `web/server/templates/layout.html`, delete the line `<script src="{{ js_resource_url('bootstrap-5.2.0.js') }}"></script>`. Keep the jQuery line above it. (blocks unit 5) Done on `mig/WP-0e-dead-frontend-code-backend` (backend-3).
- [x] backend: R4. In `web/server/templates/query_app_vendor_scripts.html`, delete the first two lines: `<script src="{{ js_resource_url('bootstrap-datepicker-1.5.1.js') }}"></script>` and `<script src="{{ js_resource_url('bootstrap-select-1.12.2.patched.js') }}"></script>`. Keep d3, rbush, acorn and polyfill. (blocks unit 6) Done on `mig/WP-0e-dead-frontend-code-backend` (backend-3).
- [ ] frontend-design: R5. Delete `web/public/scss/vendor/bootstrap-datepicker-1.5.1.scss` and `web/public/scss/vendor/bootstrap-select-1.9.4.scss`; delete the two lines `@import 'vendor/bootstrap-datepicker-1.5.1';` and `@import 'vendor/bootstrap-select-1.9.4';` from `web/public/scss/entry.scss`; delete the `.bootstrap-select.btn-group .dropdown-toggle .caret { ... }` rule in `web/public/scss/overrides/_smartadmin_overrides.scss` (lines 118-123); delete the nested `.bootstrap-select > .dropdown-toggle { ... }` rule in `web/public/scss/components/visualizations/_visualization_container.scss` (lines 22-28). Every selector in those files is scoped to classes only the two jQuery plugins create. Check: `yarn build`. (blocks unit 6)

### Requests addressed to the human lead

- [ ] human: Should Alerts be revived or deleted? `/alerts` and `/<locale>/alerts` render `notfound.html` today (`web/server/routes/index.py`, `alerts()`), while webpack still builds the `alerts` entry (`web/client/entryPoints/alertsAppEntry.js`). This WP leaves the route, the entry and the Alerts code as they are until product answers.

## Log

- 2026-10-04 frontend-platform-1 unit 1: removed papaparse, simple-statistics, d3-random, d3-scale-chromatic and their flow-typed stubs (37475f2); check: `yarn install --frozen-lockfile` and `yarn build` pass on host Node 24 and in the node:18.17 image, Flow error set identical to `main`, bundles identical to `main`.
- 2026-10-04 frontend-platform-1 unit 2: navbar entry comment no longer points at `query.html` (da8d8a3); check: eslint clean, executable JS identical to `main`.
- 2026-10-04 frontend-platform-1: units 3 to 7 blocked on R1 to R5.
- 2026-10-04 backend-3 R1: deleted `query.html` and `facilities_map.html` (ef6e987); check: no render call, `extends` or `include` names either file anywhere in the repo outside `docs/` (`web/server`, `web/python_client`, `web/client`, `scripts`, `config`); every remaining template still compiles.
- 2026-10-04 backend-3 R2: removed the `is_screenshot_request` `asyncMapChunk.bundle.js` block and its comment from `grid_dashboard.html`; check: rendered output loses only that tag. `is_screenshot_request` is still used by `layout.html` (the `screenshot-page` body class), so `template_renderer.py` keeps passing it.
- 2026-10-04 backend-3 R3: removed `bootstrap-5.2.0.js` from `layout.html`; check: rendered output of every page template loses only that tag.
- 2026-10-04 backend-3 R4: removed `bootstrap-datepicker-1.5.1.js` and `bootstrap-select-1.12.2.patched.js` from `query_app_vendor_scripts.html`; check: rendered output loses only those two tags, and d3, rbush, acorn and polyfill stay.

## Evidence

- **Nothing imports the removed packages.** `grep -rlE "papaparse|simple-statistics|d3-random|d3-scale-chromatic" --exclude-dir=node_modules .` now matches only planning docs and a URL comment in `web/client/components/ui/visualizations/LineGraph/models/LineGraphTheme.js` (a link to d3's category10 source, no import). `yarn.lock` loses exactly those four entries and nothing else.
- **Shipped build path.** `docker build -f docker/web/Dockerfile_web-client .` (node:18.17, `yarn install --frozen-lockfile --pure-lockfile`, then `yarn run build`) passes for `main` and for this branch. Both builds were extracted from `/client/build` and compared with `diff -rq`. Every bundle, chunk, CSS file, font and image is byte-identical. The only differences are `navbar.bundle.js` (its trailing `//# sourceMappingURL=` line), its source map, and `sourcemap.json`, because the source map embeds the edited comment. With the `sourceMappingURL` line stripped, `navbar.bundle.js` is identical too.
- **Host build.** `NODE_OPTIONS=--dns-result-order=ipv4first yarn install --frozen-lockfile --ignore-scripts` then `yarn build`: webpack 5.80.0 compiled with the same 2 warnings as `main`, in 39 s. `--ignore-scripts` is needed because `node-pty` 0.10 (a dependency of the dev-only `stylelint_d`) does not compile on Node 24. This affects `main` too and is not caused by this WP.
- **Flow.** `flow check` reports the same 19 errors on `main` (stubs restored) and on this branch (stubs deleted), with an identical sorted list of error locations. None mention the removed modules.
- **No `asyncMapChunk`.** The build emits 29 `*.bundle.js` files, and none is `asyncMapChunk.bundle.js`. No `webpackChunkName` exists in `web/client`. This supports R2.
- **Bundle sizes per entry, in bytes.** These are the same on `main` and on this branch: admin 141339, advancedQuery 322400, alerts 23201, dashboardBuilder 457088, dataCatalog 182167, dataDigest 30338, dataQuality 101760, dataUpload 110659, embeddedQuery 19655, fieldSetup 82342, forgotPasswordPage 4066, loginPage 4730, navbar 2165, newUserButton 5234, notFoundPage 3267, overviewPage 30198, registerPage 5701, resetPasswordPage 5071, unauthorizedPage 2567. Shared bundles: vendor 973134, commons 1667585, CSS 477708.
- **Page check not run.** The 15 page routes were not checked with `verify` against a running app. The Flask app cannot start without a live Druid that already holds a datasource: `_create_app_internal` in `web/server/app.py` calls `update_db_datasource` and `initialize_druid_context`. That means a `harmony_demo` pipeline run plus Druid, Postgres and Hasura, and the stack's fixed host ports (80, 443, 5000, 6379, 8088) clash with other projects on this host. For units 1 and 2 the byte-identical executable bundles show that runtime cannot change. Units 5 and 6 change which scripts the pages load, so they still need the page check (unit 7) once R3 and R4 land. That check should run on the QA harness (WP-2e) or on a stack with demo data.
- **Deslop.** I reviewed the diff by hand: it is deletions plus one rewritten doc comment, with no narration.
- **R1 to R4 templates (backend-3).** Every file under `web/server/templates` was compiled and rendered with Jinja2 3 before and after the change. Undefined names and helpers were stubbed, and each template was rendered with `is_screenshot_request` both false and true. All 34 files compile before and all 32 compile after. `diff -r` of the rendered output shows only removed `<script>` tags (`bootstrap-5.2.0.js` from every page that extends `layout.html`; `bootstrap-datepicker`/`bootstrap-select` from every page that includes `query_app_vendor_scripts.html`; `asyncMapChunk.bundle.js` only from `grid_dashboard.html` with `is_screenshot_request` true) plus the outputs of the two deleted templates. Seven email and `auth/user_profile` templates do not render under this harness (they need the app's `flask_user` loader and repo-root paths). That fails identically before and after, and none of them touches the changed files. `grep -rnE "asyncMapChunk|bootstrap-5\.2\.0|bootstrap-datepicker|bootstrap-select|['\"/](query|facilities_map)\.html" --exclude-dir={node_modules,.git,docs,public} .` returns nothing. Under `web/public` the only matches are the vendor scripts (frontend-platform units 5 and 6) and the SCSS in R5.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | n/a | |
