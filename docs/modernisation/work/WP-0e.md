---
wp: "0e"
title: "Delete dead frontend code and dependencies"
status: review
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
- [x] frontend-design: R5 (done on `mig/WP-0e-dead-frontend-code-design`, bfdf14d). Delete `web/public/scss/vendor/bootstrap-datepicker-1.5.1.scss` and `web/public/scss/vendor/bootstrap-select-1.9.4.scss`; delete the two lines `@import 'vendor/bootstrap-datepicker-1.5.1';` and `@import 'vendor/bootstrap-select-1.9.4';` from `web/public/scss/entry.scss`; delete the `.bootstrap-select.btn-group .dropdown-toggle .caret { ... }` rule in `web/public/scss/overrides/_smartadmin_overrides.scss` (lines 118-123); delete the nested `.bootstrap-select > .dropdown-toggle { ... }` rule in `web/public/scss/components/visualizations/_visualization_container.scss` (lines 22-28). Every selector in those files is scoped to classes only the two jQuery plugins create. Check: `yarn build`. (blocks unit 6)

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
- 2026-10-04 frontend-design-1 R5: deleted the bootstrap-datepicker and bootstrap-select vendor SCSS, their two imports and the two `.bootstrap-select` overrides (bfdf14d, branch `mig/WP-0e-dead-frontend-code-design`). This is a pure deletion with no visual change, so the `/frontend-design:frontend-design` workflow was not needed. Check: stylelint clean; `yarn build` compiles with the same 2 warnings; built CSS loses exactly 111 plugin-scoped rules and gains none; JS bundles are byte-identical.
- 2026-10-04 frontend-platform-1: merged `mig/WP-0e-dead-frontend-code-backend` (08337c2) and `mig/WP-0e-dead-frontend-code-design` (f979ad4); units 3 and 4 are done by R1 and R2.
- 2026-10-04 frontend-platform-1 units 5 and 6: deleted `bootstrap-5.2.0.js`, `bootstrap-datepicker-1.5.1.js` and `bootstrap-select-1.12.2.patched.js` from `web/public/js/vendor/` and `vendor/min/` (5522214); check: zero references repo-wide; `yarn install --frozen-lockfile` and `yarn build` pass on host Node 24 and in the node:18.17 image; JS bundles identical to `main`, CSS loses only plugin rules.
- 2026-10-04 frontend-platform-1 unit 7: every page template rendered with Jinja2 on `main` and on this branch; the output differs only by the removed script tags, and every remaining script URL resolves to a file. The running-app check is deferred to the QA harness (WP-2e), see Evidence.

## Evidence

- **Nothing imports the removed packages.** `grep -rlE "papaparse|simple-statistics|d3-random|d3-scale-chromatic" --exclude-dir=node_modules .` now matches only planning docs and a URL comment in `web/client/components/ui/visualizations/LineGraph/models/LineGraphTheme.js` (a link to d3's category10 source, no import). `yarn.lock` loses exactly those four entries and nothing else.
- **Shipped build path (units 1 and 2).** `docker build -f docker/web/Dockerfile_web-client .` (node:18.17, `yarn install --frozen-lockfile --pure-lockfile`, then `yarn run build`) passes for `main` and for this branch. Both builds were extracted from `/client/build` and compared with `diff -rq`. Every bundle, chunk, CSS file, font and image is byte-identical. The only differences are `navbar.bundle.js` (its trailing `//# sourceMappingURL=` line), its source map, and `sourcemap.json`, because the source map embeds the edited comment. With the `sourceMappingURL` line stripped, `navbar.bundle.js` is identical too.
- **Host build.** `NODE_OPTIONS=--dns-result-order=ipv4first yarn install --frozen-lockfile --ignore-scripts` then `yarn build`: webpack 5.80.0 compiled with the same 2 warnings as `main`, in 39 s. `--ignore-scripts` is needed because `node-pty` 0.10 (a dependency of the dev-only `stylelint_d`) does not compile on Node 24. This affects `main` too and is not caused by this WP.
- **Flow.** `flow check` reports the same 19 errors on `main` (stubs restored) and on this branch (stubs deleted), with an identical sorted list of error locations. None mention the removed modules.
- **No `asyncMapChunk`.** The build emits 29 `*.bundle.js` files, and none is `asyncMapChunk.bundle.js`. No `webpackChunkName` exists in `web/client`. This supports R2.
- **Bundle sizes per entry, in bytes.** These are unchanged from `main` after every unit: admin 141339, advancedQuery 322400, alerts 23201, dashboardBuilder 457088, dataCatalog 182167, dataDigest 30338, dataQuality 101760, dataUpload 110659, embeddedQuery 19655, fieldSetup 82342, forgotPasswordPage 4066, loginPage 4730, navbar 2165, newUserButton 5234, notFoundPage 3267, overviewPage 30198, registerPage 5701, resetPasswordPage 5071, unauthorizedPage 2567. Shared bundles: vendor 973134, commons 1667585. CSS is 477708 on `main` and 455612 after R5.
- **Deslop.** I reviewed the diff by hand: it is deletions plus one rewritten doc comment, with no narration.
- **Final build after all units (frontend-platform-1).** `docker build -f docker/web/Dockerfile_web-client .` on node:18.17 for HEAD 5522214, with `/client/build` diffed against the `main` image built earlier this session.
  - Every `*.bundle.js` is byte-identical except `navbar.bundle.js`, which differs only in its `sourceMappingURL` line (unit 2).
  - `bundle.css` goes from 477708 to 455612 bytes, the R5 deletion. Its rule-level diff is in frontend-design-1's entry below.
  - `sourcemap.json` loses the six hashed copies of the deleted vendor scripts (the build copies `web/public/js` into `build/min/js/vendor`) and the two deleted SCSS files. Its other changes are hash renames of the edited SCSS files, the CSS bundle and the navbar map.
  - `/client/js/vendor/min/` in the image holds 15 scripts, none of them Bootstrap.
  - On the host (Node 24, `yarn install --frozen-lockfile --ignore-scripts`), `yarn build` compiles with the same 2 warnings as `main`.
- **No references remain.** `grep -rnE "bootstrap-5\.2\.0|bootstrap-datepicker|bootstrap-select|selectpicker|asyncMapChunk|facilities_map|['\"/]query\.html" --exclude-dir=node_modules --exclude-dir=docs --exclude-dir=build --exclude-dir=agent-memory .` returns nothing (exit 1).
- **Template render check (unit 7).**
  - **Method.** `web/server/templates` was exported from `main` and from HEAD with `git archive`. Each page template was then rendered with Jinja2 3.1.6, with `is_screenshot_request` both false and true. The stubs were `config` (`VENDOR_SCRIPT_PATH=/js/vendor/min/`, `IS_PRODUCTION=False`), `sourcemap={}`, `url_for`, `get_flashed_messages` and `pass_to_js`, with `ChainableUndefined` for everything else.
  - **Coverage.** 21 templates render on `main`: admin, advanced_query, data_catalog, data_catalog_changes, data_digest, data_quality, data_status, data_upload, embedded_query, facilities_map, field_setup, forgot_password, grid_dashboard, layout, login, notfound, overview, query, register, reset_password, unauthorized. 19 render on the branch, because two were deleted. There are 0 failures on either side. The `emails/` and `auth/` templates are excluded because they need the app's `flask_user` loader and none of them uses a changed file. `query_app_vendor_scripts.html` is a partial; it is covered through the 12 pages that include it.
  - **Diff.** `diff -r` of the rendered output shows only:
    - the `bootstrap-5.2.0.js` tag, removed from the 18 remaining outputs built on `layout.html`;
    - the `bootstrap-datepicker` and `bootstrap-select` tags, removed from the 12 remaining pages that include `query_app_vendor_scripts.html`;
    - `asyncMapChunk.bundle.js`, removed from `grid_dashboard.html` only when `is_screenshot_request` is true;
    - the outputs of the two deleted templates.
  - **Script URLs.** All 26 distinct script URLs in the branch's rendered pages resolve to a file in the build output or `web/public/js`. On `main`, `/build/asyncMapChunk.bundle.js` did not resolve.
- **Deferred to the QA harness (WP-2e).** These need the running app, which needs Druid with `harmony_demo` data, Postgres and Hasura, and could not be started this session:
  - every page route at 390, 1024 and 1440 px with no console errors (`verify`), in particular the 18 pages that no longer load Bootstrap 5 JS and the 12 that no longer load bootstrap-select and bootstrap-datepicker;
  - a dashboard screenshot or export with a map tile (`is_screenshot_request`), to confirm that dropping the never-built `asyncMapChunk` tag leaves map tiles rendering as before;
  - a visual pass on pages using the query form, data quality and visualization controls, to confirm the 111 removed plugin CSS rules styled nothing on screen.
- **Deslop (units 5 to 7).** The diff is six file deletions plus the WP file; there is nothing to narrate.
- **R1 to R4 templates (backend-3).** Every file under `web/server/templates` was compiled and rendered with Jinja2 3 before and after the change. Undefined names and helpers were stubbed, and each template was rendered with `is_screenshot_request` both false and true. All 34 files compile before and all 32 compile after. `diff -r` of the rendered output shows only removed `<script>` tags (`bootstrap-5.2.0.js` from every page that extends `layout.html`; `bootstrap-datepicker`/`bootstrap-select` from every page that includes `query_app_vendor_scripts.html`; `asyncMapChunk.bundle.js` only from `grid_dashboard.html` with `is_screenshot_request` true) plus the outputs of the two deleted templates. Seven email and `auth/user_profile` templates do not render under this harness (they need the app's `flask_user` loader and repo-root paths). That fails identically before and after, and none of them touches the changed files. `grep -rnE "asyncMapChunk|bootstrap-5\.2\.0|bootstrap-datepicker|bootstrap-select|['\"/](query|facilities_map)\.html" --exclude-dir={node_modules,.git,docs,public} .` returns nothing. Under `web/public` the only matches are the vendor scripts (frontend-platform units 5 and 6) and the SCSS in R5.
- **R5 SCSS deletion (frontend-design-1).**
  - **Scope.** Every top-level selector in the two vendor files names a plugin-only class: `datepicker`, `input-daterange`, `input-append`/`input-prepend`, `bootstrap-select` or `bs-*`. Neither file nests rules.
  - **No users.** A case-sensitive `grep -rnE "bootstrap-select|selectpicker|bs-searchbox|bs-actionsbox|bs-donebutton|bs-container|datepicker|input-daterange|input-append|input-prepend|show-menu-arrow|filter-option" web/client web/server/templates` matches only the two `<script>` tags in `query_app_vendor_scripts.html` (R4).
  - **Unchanged source before the edit.** `git diff main -- web/public/scss web/webpack*.js` was empty on the base branch, so the baseline CSS equals `main`'s. It is 477708 bytes, the same as the size recorded above.
  - **Build.** Host Node 24, `yarn install --frozen-lockfile --ignore-scripts`, then `yarn build` before and after. Both compile with the same 2 warnings. CSS goes from 477708 to 455612 bytes.
  - **Rule-level diff.** Both CSS files were parsed with postcss into one line per rule, including the at-rule context. The after-list is the before-list minus 111 rules, in the same order, with 0 added. The removed rules are 55 from the datepicker family and 56 from the bootstrap-select family. Among them are both overrides, `.bootstrap-select.btn-group .dropdown-toggle .caret{margin-top:0;...}` and `.visualization-container .controls .bootstrap-select>.dropdown-toggle{...}`. No removed rule lacks a plugin class.
  - **JS.** Every `*.bundle.js` is byte-identical before and after.
  - **Lint.** `stylelint` on the three edited SCSS files is clean.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | approved | 2026-10-04 qa-0e: lockfile drops only the four packages; JS bundles identical except navbar source-map line; CSS loses exactly 111 plugin-only rules; rendered pages lose only dead script tags; every script URL resolves; headless Chromium console identical except removed 404s. Running-app check deferred to WP-2e; Alerts to the human. Note: auth/layout.html also extends layout.html (20 templates, not 18). |
| reviewer | pending | |
| security | n/a | |
