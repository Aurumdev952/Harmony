# 0015. WP-6a: supporting roles for the bluebird and jQuery removal

Status: applied by the lead on 2026-10-06, pending human ratification (SPEC section 10).

## Context

WP-6a (`fetch` instead of jQuery and bluebird, owner frontend-platform, branch `mig/WP-6a-fetch-no-jquery` at 92f0671c) moved the services and clients to `fetch` and native promises, but cannot delete bluebird and jQuery: code under `web/client/components/**` calls bluebird-only promise methods (`isPending`, `cancel`, `isCancelled`, `disposer`, `Promise.using`) on the promises those services return, and `fetchGeoJsonTiles` still uses jQuery. If the producers go native first, every visualization crashes. The callers must move first, and their paths belong to frontend-design (components outside visualizations), visualization (visualizations, ui/visualizations, QueryResult) and backend (`layout.html`, the last script tags). SPEC row 6a lists no supporting role, so `task_gate.py` would refuse the WP once those roles' commits are in its branch.

## Decision

1. SPEC row 6a gains the supporting roles **frontend-design, visualization, backend**, each limited to the files WP-6a's Requests name: frontend-design runs the codemod on `web/client/components/**` outside the visualization paths and hand-fixes the remainder (including the `DataDigestApp` catch WP-2e asked for and the toastr preload in `Navbar`); visualization rewrites `QueryResult` and `QueryInterface` onto native promises and moves `fetchGeoJsonTiles` to `fetch`; backend drops the jQuery script tag and loads the jQuery-free `toastr.js` in `layout.html` once the last jQuery call is gone.
2. Order: callers first (frontend-design and visualization side branches merged by the owner), then backend, then the owner's unit 7 (delete bluebird, jQuery, toastr 2.1.2 and the Flow stubs) with full Flow, lint, unit, e2e and bundle-size evidence.
3. The toastr replacement renders messages as text where toastr 2.1.2 rendered HTML; two messages carry user input (a role name and a URL). This is a deliberate narrowing and the reviewer confirms no message depended on HTML.

## Consequences

- SPEC section 5 row 6a: Supporting = frontend-design, visualization, backend; version bumped to 1.15.
- The WP-2e ESLint flat-config request (FE-11) stays with WP-6e; `data_catalog_changes.html`'s CDN jQuery and Bootstrap go with WP-7h.
- Human: ratify with the other decisions.
