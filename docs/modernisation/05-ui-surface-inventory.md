# 05. UI surface inventory

Back to [overview](overview.md). Phase plan: [phase-7-design-system.md](phase-7-design-system.md).

This lists every screen and every `web/client/components/ui` module that the HeroUI and Urbanist redesign touches. Counts come from grep and `wc` on 2026-10-04 and exclude `__generated__`. Re-run them before each wave starts. The script lives in phase 7a.

## Screens

Every page is a Jinja template that extends `web/server/templates/layout.html` and mounts one React bundle. Order is the column that says when each screen moves (see phase 7).

| Order | Surface | Entry / template | Views | Size (files / LOC) | Complexity | Notes |
|---|---|---|---|---|---|---|
| 1 | App shell and navbar | `navbar`, `layout.html` | Navbar, dashboards flyout, navigation dropdown, more links, collapse at 1250px, session-timeout toasts | 9 / 1,845 | Medium | On every page, so it sets the visual language. Uses toastr directly. |
| 2 | Auth | `loginPage`, `registerPage`, `forgotPasswordPage`, `resetPasswordPage` | `AuthLayout`, `FormInput`, four forms | 13 / 1,080 | Low | Also drop the Flask-User fallback templates `auth/login.html` and `auth/user_profile.html`. |
| 2 | Error pages | `notFoundPage`, `unauthorizedPage` | Static | 4 / 201 | Trivial | |
| 3 | Overview (home) | `overview.html` | Official dashboard cards, tabbed dashboard table, favourites | 7 / 881 | Low | First real use of Card, Tabs and Table together |
| 4 | Admin | `admin.html` | Users, Groups, Role management, Site configuration, access selection, invite, delete and role modals | 70 / 11,348 | High | Many forms and tables. A good proving ground for Table, Modal and Select. |
| 4 | Field Setup | `field_setup.html` | Unpublished fields bulk-edit table, header actions | 25 / 2,314 | Medium | Moves off Relay in phase 5 |
| 4 | Data Digest | `data_digest.html` | Datasource overview, pipeline overview, datasource dropdown, XLS download | 18 / 1,275 | Low-medium | |
| 4 | Data Upload | `data_upload.html` | Data status page, source table, the `AddDataModal` wizard | 44 / 6,843 | High | Multi-step wizard with file upload. Moves off Relay in phase 5. |
| 4 | Alerts | `alerts` entry (route renders 404 today) | Definitions tab, notifications tab, compose modal | 13 / 1,717 | Low | Product decides whether to revive or delete it. Phase 0 asks. |
| 5 | Data Catalog | `data_catalog.html` | Directory tree and table, field details page, shared catalog components | 112 / 9,309 | High | Hierarchy browsing. The biggest Relay user (21 generated folders). |
| 5 | Data Quality Lab | `data_quality.html` | Summary, reporting completeness, outlier analysis, indicator characteristics | 30 / 5,992 | Medium-high | Chart-heavy. Outliers bug fixed in phase 1. |
| 6 | Analyze (AQT) | `advanced_query.html` | Query form panel, live results view with share modal, query tabs, shared `QueryBuilder`, viz settings modal (General, Axes, Series, Legend) | 105 / 10,182, plus `common/QueryBuilder` 51 / 3,800 | High | The core loop. Redesign with real users in the room. |
| 6 | Embedded query | `embedded_query.html` | Result viewer inside an iframe | 6 / 357 | Low | Embedding constraints. No shell chrome. |
| 7 | Dashboard Builder | `grid_dashboard.html` | Grid (react-grid-layout), tile container, fullscreen tile, common settings panel, header with edit and present controls, settings, share and clone modals, embedded and screenshot modes | 161 / 15,292 | Very high | Drag and resize, zoom, presentation, export. Pixel-check against the screenshot mode. |
| 8 | Jinja-only pages | `data_status.html`, `data_catalog_changes.html` | Bootstrap 3 panel and table; tabbed diff report | 56 and 117 lines | Low | Port to React routes or delete. |
| — | Emails | `templates/emails/*.html` (7) | Transactional emails | — | — | Brand colours and font only |

Shared code reused across screens:
- `components/common` (123 / 12,400): `SharingUtil`, `CustomCalculationsModal`, `DashboardPickerModal`, `UserSelect`.
- `components/visualizations` (212 / 24,800).
- `components/QueryResult` (9 / 1,200).

## `ui/` modules

401 files and 39,252 LOC. Importers counts distinct files outside the module that import `components/ui/<Name>`.

### Replaced by HeroUI

| Module | Importers | HeroUI v3 | Watch for |
|---|---|---|---|
| Dropdown (+Multiselect, Uncontrolled, Option, OptionsGroup) | 67 | Select, Autocomplete, ComboBox | Async search (`onAsyncSearch`), grouped results, multiselect, debounce. 23 files / 3,400 LOC. Moves last among the primitives. |
| Toaster | 60 | Toast | Fold toastr in too (29 references in 6 files, plus Jinja flash messages) |
| InputText | 52 | Input / SearchField | Debounce and key handling |
| Button | 47 | Button | |
| Popover | 43 | Popover | Custom positioning (2,000 LOC). 12 `ui/` modules depend on it. |
| LabelWrapper | 43 | Field label and description | |
| InfoTooltip | 39 | Tooltip with an icon trigger | |
| Checkbox | 38 | Checkbox | |
| Table | 36 | Table and Pagination, with TanStack Table where sorting or search is heavy | 1,300 LOC |
| BaseModal | 34 | Modal | Built on react-modal today |
| Tooltip | 32 | Tooltip | |
| LoadingSpinner | 30 | Spinner | |
| ProgressBar | 20 | ProgressBar | |
| Tag | 19 | Chip / TagGroup | |
| RadioGroup | 19 | RadioGroup | |
| Tabs | 19 | Tabs | |
| Intents, LegacyIntents | 11 | Button and Chip `color` | |
| Well | 8 | Card | |
| ToggleSwitch | 8 | Switch | |
| LegacyButton | 7 | Button | Migrate callers, then delete |
| RemoveItemButton, IconButton | 14 | Button `isIconOnly` | |
| TabbedModal | 7 | Modal with Tabs | |
| Alert | 7 | Alert | |
| AnimateHeight | 6 | Accordion / Disclosure | |
| FallbackPill | 5 | Chip | |
| Card | 5 | Card | |
| Breadcrumb | 4 | Breadcrumbs | |
| PageSelector | 3 | Pagination | |
| HypertextLink | 3 | Link | |
| RangeSlider | 2 | Slider (range) | Custom drag logic today |
| ProgressModal | 2 | Modal with ProgressBar | |
| List | relative imports only | ListBox | |
| BorderlessInputText | 1 | Input with an underlined variant | |
| Accordion | 1 | Accordion | |

### Replaced by Tailwind utilities

| Module | Importers | Replacement |
|---|---|---|
| Group | 181 | `flex` and `gap-*`, by codemod |
| Heading | 75 | Typography utilities over tokens |
| Spacing | 39 | Spacing utilities, by codemod |
| Caret | 18 | Icon |

### Kept and restyled on tokens

| Module | Importers | Approach |
|---|---|---|
| Icon | 98 | Today it emits Bootstrap glyphicon classes (42 glyph types in use) plus 88 SVGs. Map each glyph to Lucide in a lookup table, keep the `Icon` API, then remove the glyphicon font. |
| visualizations | 65 | Restyle with tokens. Library swaps are listed under "Charts" below. |
| DatePicker | 13 | Keep the shell, which holds the relative editors (since, between, year to date) and the Ethiopian selector. Use HeroUI DatePicker and RangeCalendar inside it, with `@internationalized/date` `EthiopicCalendar`. Remove react-day-picker 7 and moment. 3,700 LOC. |
| ColorBlock | 13 | Use HeroUI's colour picker if it covers swatch and hex entry. Otherwise keep it and drop react-color. |
| DraggableItem, DraggableItemList | 12 | React Aria drag and drop, replacing HTML5 drag events and react-draggable |
| HierarchicalSelector, HierarchicalSelectorDropdown | 8 | Column drill-down with search and keyboard navigation. Restyle it, and evaluate React Aria `Tree` for the list column. 2,300 LOC. |
| UploadInput | 3 | React Aria `DropZone` and `FileTrigger` |
| TextHighlighter | 2 | Keep |
| Colors, `colors.md` | 11 | Replaced by generated tokens |
| Styleguidist `*.md` | — | Replaced by Storybook on Vite (or Ladle) |

## Styling to retire

There are 243 SCSS files with 21,120 lines in total:

| Group | Files | Fate |
|---|---|---|
| Vendor (Bootstrap 3, bootstrap-select, bootstrap-datepicker, toastr, react-table 6, literallycanvas, flags, cursors) | 43 | Delete as each dependency leaves |
| Overrides (`bootstrap_*`, `smartadmin_*`, `plotly_overrides`, `select_overrides`) | 7 | Delete in phase 7h |
| Globals (`_zen_variables`, `_zen_variables_legacy`, `_zen_typography`, `_zen_fonts`, `_zen_main`, `_zen_mixins`, `entry.scss`) | 7 | Tokens move to `tokens.css`. The rest is deleted last. |
| `components/ui` | 48 | Deleted with each `ui/` module |
| `components/visualizations` and `ui/visualizations` | 19 | Moved to Tailwind classes on the chart containers |
| Page styles (`gd-`, `aqt-`, `dc-`, `dq-`, `fs-`, `gis-` prefixes) | about 110 | Deleted page by page as each surface moves |

How SCSS and Tailwind coexist while both are present:
- Tailwind v4 preflight is turned off while Bootstrap 3 globals are loaded. It is turned back on once `bootstrap_overrides` is gone.
- HeroUI styles are scoped under a `.hui` root class on migrated surfaces, so old global element rules do not leak into new components.

### Bootstrap and jQuery coupling

- **Bootstrap classes in JSX are rare:** about 50 uses across a dozen files. Most coupling runs through `Icon`.
- **`layout.html` loads Bootstrap 5 JS, but nothing uses it.** Delete it in phase 0.
- **jQuery has four call sites,** and all of them carry load: `APIService.js:71`, `ZenClient.js:12`, `fetchGeoJsonTiles.js` and a comment in `ScriptLoaderService.js`. Phase 6a replaces them with `fetch`.

## Charts

| Chart | Renderer today | Target |
|---|---|---|
| BarGraph, Histogram, BoxPlot, BumpChart, EpiCurve, NumberTrend, PieChart, LineGraph (ui) | @vx 0.0.195 (27 files) | visx (renamed successor with the same API) |
| LineGraph (product), BubbleChart, HeatTiles | Plotly 1.22 global (9 files) | visx |
| Sunburst, ExpandoTree | d3 v3 global (7 files) | `d3-hierarchy` v3 with visx |
| MapCore, MapViz | react-map-gl 6 and mapbox-gl (20 files) | react-map-gl 8 with MapLibre. That removes the Mapbox token and its usage billing. Add deck.gl only for heavy layers. |
| Table viz | react-window | Keep, restyle |

Chart fonts are set in JavaScript theme objects (`LABEL_FONT`, `titleFontFamily`, `textFont()`). Those objects switch to `--font-numeric` for axes and values and `--font-sans` for titles. The export path in `SharingUtil/canvas_util.js` inlines font files, so it needs the new WOFF2 files too.
