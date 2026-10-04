# Phase 7. Design system: HeroUI v3 and Urbanist

Back to [overview](overview.md). Surfaces: [05-ui-surface-inventory.md](05-ui-surface-inventory.md). Design: [03-target-architecture.md](03-target-architecture.md#design-system).

**Goal.** Redesign every screen on HeroUI v3, Tailwind v4 and Urbanist, and end with a single-page app that works offline. Use the `frontend-design:frontend-design` skill for visual direction and the `verify` skill for each surface.

**Prerequisites.** Phase 6c (React 19) has landed. The browser share from phase 0g supports Tailwind v4's baseline.

## 7a. Typography prototype and the surface script

- **Changes.**
  - Build a throwaway page with three real views rendered in each figure-face option: a dashboard KPI row, a 200-row table and a line chart's axes. The options are listed in [03-target-architecture.md](03-target-architecture.md#typography).
  - Run it with `pstack:arena` and decide on screenshots, in Latin and Amharic.
  - Commit the decision to the decision log.
  - Add `scripts/frontend/surface_report.mjs`, which reprints the importer counts from the inventory. Each wave starts by running it.
- **Verification.** The screenshots and the chosen option are committed to `docs/modernisation/decisions/`.

## 7b. Tokens, fonts and the theme

- **Changes.**
  - Add `web/client/design/tokens.css` with Tailwind v4 `@theme` and HeroUI theme variables, built from `_zen_variables.scss` and then adjusted by the redesign.
  - Generate `Colors.js` from the tokens so chart code keeps its JavaScript API.
  - Self-host Urbanist, the figure face and Noto Sans Ethiopic through Fontsource. Load the Ethiopic subset only when the locale needs it.
  - Turn Tailwind preflight off while Bootstrap 3 globals are present.
  - Scope HeroUI under a `.hui` root.
  - Add a lint rule that bans hex colours outside `tokens.css`.
- **Data structure.** Token groups: `color.*`, `font.sans`, `font.numeric`, `radius.*`, `space.*`, `shadow.*`, `z.*`.
- **Verification.** A Storybook page shows every token. Contrast is checked with axe for each colour role in light mode.

## 7c. Shell, authentication, error pages and Overview

- **Changes.**
  - Rebuild the navbar and app shell on HeroUI. It runs in every entry.
  - Rebuild the four auth pages and the two error pages.
  - Fold toastr and the Jinja flash messages into HeroUI Toast through one `notify()` API.
  - Rebuild Overview.
- **Verification.**
  - `verify` on each page at 1440, 1024 and 390 pixels wide.
  - axe reports no serious or critical violations.
  - The Playwright auth flows pass.

## 7d. Primitives behind their existing APIs

- **Changes.**
  - Swap the internals of these `ui/` modules to HeroUI, keeping their props: Button, InputText, Checkbox, RadioGroup, ToggleSwitch, Tag, Tooltip, InfoTooltip, LoadingSpinner, ProgressBar, Tabs, Alert, Card, Well, Breadcrumb, PageSelector, HypertextLink.
  - Then BaseModal and TabbedModal.
  - Then Toaster.
  - Then Popover, which 12 `ui/` modules depend on.
  - Then Dropdown, moved to Select and Autocomplete with async search.
  - Map `Icon` glyphicons to Lucide through a lookup table and delete the glyphicon font.
  - Replace `Group`, `Spacing`, `Heading` and `Caret` with Tailwind utilities by codemod.
- **Verification.**
  - Run Storybook interaction tests for each primitive.
  - Do a Playwright visual pass over every page after each primitive, so regressions surface where the primitive is used and not in a later page wave.

## 7e. Pages, in waves

Each wave moves its screens onto HeroUI's own APIs. As each wave finishes, it deletes the `ui/` wrappers and SCSS partials that no screen imports any more. Order follows the inventory.

1. Admin, Field Setup, Data Digest, Data Upload, and Alerts (if kept).
2. Data Catalog and Data Quality Lab. Restyle `HierarchicalSelector` here. Rebuild `DatePicker` on HeroUI calendars with `EthiopicCalendar`.
3. Analyze (AQT) and the embedded query. Redesign the query form and the viz settings modal with real users in a review session.
4. Dashboard Builder. Grid, tiles, presentation mode and the share, clone and settings modals, plus the screenshot and embedded modes.

- **Verification for each wave.**
  - Run `verify` on every screen in the wave.
  - Run the Playwright smoke suite and axe.
  - Compare screenshots of the export path against the phase 1h renderer.
  - `surface_report.mjs` shows importer counts falling to zero for every module the wave replaced, and those modules are deleted.

## 7f. Single-page shell and offline use

- **Changes.**
  - Collapse the entries into one `index.html` with TanStack Router routes that keep every existing URL.
  - Move from `window.__JSON_FROM_BACKEND` to the `/api/v3/session/bootstrap` query.
  - Turn embedded and screenshot modes into route layouts.
  - Add `vite-plugin-pwa`:
    - precache the shell and fonts,
    - keep the field catalog in IndexedDB,
    - use stale-while-revalidate for the results of recently opened dashboards,
    - show a visible "offline, showing data from <time>" state.
  - Delete the Jinja page templates.
- **Verification.**
  - Every old URL resolves (Playwright URL table).
  - Navigating between apps does not reload the document.
  - With the network disabled in Playwright, a previously opened dashboard renders from cache with the offline banner.

## 7g. Charts and maps

- **Changes.**
  - Switch every `@vx/*` import to `@visx/*` (27 files).
  - Rebuild the Plotly line graph, bubble chart and heat tiles on visx, then delete Plotly 1.22.
  - Rebuild Sunburst and ExpandoTree on `d3-hierarchy`, then delete the d3 v3 global.
  - Move maps to react-map-gl 8 with MapLibre and self-hosted or OpenFreeMap tiles, and remove the Mapbox token.
  - Chart theme objects read `--font-numeric` and `--font-sans`.
- **Verification.**
  - Golden visual tests per chart type with a fixed dataset.
  - Exports render the new fonts.

## 7h. Delete the old styling

- **Changes.** Delete the Bootstrap 3 SCSS, the override partials, the remaining page styles, `_zen_variables*.scss`, sass and its loaders. Turn on Tailwind preflight. Remove the `.hui` scope. Ship dark mode.
- **Verification.**
  - `web/public/scss` no longer exists.
  - Full Playwright and axe pass in light and dark themes.
  - Bundle sizes are recorded against the phase 6b numbers.
