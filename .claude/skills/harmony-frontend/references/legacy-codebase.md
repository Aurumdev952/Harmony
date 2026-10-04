# Legacy patterns you will meet in web/client

| Pattern | Where | What to know |
|---|---|---|
| Zen models | `web/client/lib/Zen` (ZenModel, ZenArray, ZenMap, deepUpdate), about 190 files | Immutable models with generated getters and setters. Setters return new instances. `UNSAFE_get`, `UNSAFE_deserialize` and `UNSAFE_forceGet` are Zen methods, not React APIs. Keep Zen models for query and dashboard specs. They are domain models, and the target keeps them (03-target-architecture). |
| Serialisation | `serialize()`, `serializeForQuery()`, `deserializeAsync()` on models | These shapes are stored in Postgres as dashboard specs and saved queries. Never change a serialised shape without a migration and a golden test. |
| `$ref` URIs | `models/core/wip/Dimension/index.js:115` and similar | `{$ref: '/api2/query/<endpoint>/<id>'}` is persisted data. Readers must accept it until WP-5g rewrites stored rows. |
| I18N | `web/client/lib/I18N`, `I18N.text(...)` in 451 files, generated `web/client/i18n.js` index of about 210 `i18n.js` files | Every user-visible string goes through `I18N.text` with an id. Run `yarn translations` (later `pnpm translations`) after adding strings. Moving files moves their `i18n.js`, so keep them together. |
| Server bootstrap | `window.__JSON_FROM_BACKEND`, about 35 keys, 124 reads in 79 files | Produced by `TemplateRenderer.build_lightweight_backend_js_config` (`web/server/util/template_renderer.py:164-213`). `user` and `ui` are the most read. Becomes `/api/v3/session/bootstrap` in WP-5h and WP-7f. |
| Vendor registry | `web/client/vendor/registry/index.js` with `ScriptLoaderService` | Loads d3 v3, Plotly 1.22, html2canvas, jsPDF, pptxgen, zipcelx, filesaver, literallycanvas and the acorn interpreter at runtime from `web/public/js/vendor`. literallycanvas needs `window.React`. WP-6f and WP-7g retire these. |
| Toasts | `ui/Toaster` (React) plus global `window.toastr` (6 files and Jinja flashes) | Both collapse into one HeroUI Toast `notify()` in WP-7c. |
| Ethiopian calendar | `ui/DatePicker` (`EthiopianDateSelector`, `ethiopianDateUtil`), `ethiopian-date` npm, backend `calendarSettings` | INV-5. Any date change needs tests in both calendars. |
| Session timeout | `util/timeoutSession.js`, `monitorSessionTimeout()` in `baseEntry.js` | Calls into toastr. Keep the behaviour when the shell changes. |
