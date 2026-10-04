---
name: harmony-design-system
description: Harmony's redesign on HeroUI v3, Tailwind CSS v4 and the Urbanist typeface, covering tokens, typography, component mapping, surface waves and visual verification. Use for any work under web/client/design, web/client/components (outside visualizations), web/public/scss or web/public/fonts, and for any screen redesign. Always pair it with frontend-design:frontend-design for visual direction and heroui-react for component APIs.
---

# Harmony design system

Three skills work together on every design task:
1. **`frontend-design:frontend-design`** sets the visual direction, the craft bar and the anti-generic rules. Invoke it at the start of every screen or component design, before writing markup.
2. **`heroui-react`** (vendored) covers HeroUI v3 APIs. Run its scripts for live docs instead of trusting memory:
   ```bash
   node .claude/skills/heroui-react/scripts/get_component_docs.mjs Table
   ```
   The `heroui-react` MCP server in `.mcp.json` gives the same information.
3. **This skill** holds Harmony's constraints, tokens and order of work.

## Who the product is for

Ministry of health analysts, programme managers and data managers, often on modest laptops, low-bandwidth links and older browsers, in English, French, Portuguese and Amharic.

The core loop is: pick indicators, filter and group, read a chart or table, save it to a dashboard, share it.

Density and legibility of numbers matter more than decoration. "Experience first" here means fast, calm, exact screens.

## Non-negotiables (SPEC FE-5 to FE-8)

- **HeroUI v3 only.** No `HeroUIProvider`, no `framer-motion`, no v2 flat props. Use compound components (`<Card><Card.Header>`) and `onPress`, not `onClick`. Styles come from `@heroui/styles` after `@import "tailwindcss";`.
- **Tokens only.** Every colour, radius, spacing, shadow and font comes from `web/client/design/tokens.css` (contract C-6). Hex literals anywhere else fail lint. Chart code reads tokens through the generated `Colors.ts`.
- **Typography.**
  - `--font-sans` is `"Urbanist Variable", "Noto Sans Ethiopic Variable", system-ui, sans-serif`. Use it for all text.
  - `--font-numeric` is the figure face chosen in WP-7a, with `font-variant-numeric: tabular-nums lining-nums`. Use it for table cells, KPI values, axes, tooltips, pagination and date fields.
  - Urbanist has no tabular figures, so a column of numbers in `--font-sans` is a defect.
  - Self-host every font through Fontsource. Load the Ethiopic subset only for Amharic.
- **Accessibility.** axe reports no serious or critical violations. Everything is keyboard-operable with visible focus. Text contrast is AA or better.
- **Responsive.** Every screen works at 390, 1024 and 1440 pixels wide.
- **i18n.** Every string goes through `I18N.text`. Layouts survive French and Portuguese strings that run about 30% longer.
- **Ethiopian calendar.** The DatePicker shell keeps the Ethiopian selector and the relative editors (since, between, year to date). Inside, use HeroUI calendars with `EthiopicCalendar` from `@internationalized/date`, imported directly (not `createCalendar`).

## Tailwind v4 facts

- **Configuration** goes through the `@tailwindcss/vite` plugin. Tokens live in `@theme` in `tokens.css`. Custom utilities use `@utility`. CSS modules need `@reference`.
- **Renamed utilities:**
  - `shadow-sm` became `shadow-xs`, and `shadow` became `shadow-sm`. `rounded` and `blur` shifted the same way.
  - `outline-none` became `outline-hidden`.
  - `ring` became `ring-3`.
- **Syntax.** Variables in arbitrary values are written `bg-(--x)`. The important modifier goes last (`bg-red-500!`).
- **Changed defaults.** Borders default to `currentColor`. `hover:` applies only on devices that support hover.
- **No Sass in Tailwind files.** While Bootstrap 3 SCSS still loads:
  - preflight stays off;
  - HeroUI surfaces are scoped under a `.hui` root.

  Both are removed in WP-7h.

## Order of work

[05-ui-surface-inventory.md](../../../docs/modernisation/05-ui-surface-inventory.md) is the list:
1. **7a.** Typography prototype. Compare the figure-face options on real screens (KPI row, 200-row table, chart axes) in Latin and Amharic. Decide on screenshots. Commit them to `docs/modernisation/decisions/`.
2. **7b.** `tokens.css`, generated `Colors.ts`, fonts, a Storybook token page, and the hex-literal lint.
3. **7c.** App shell and navbar, the auth pages, the error pages and Overview. Fold toastr and Jinja flashes into a single `notify()` on HeroUI Toast.
4. **7d.** Primitives behind their existing `ui/` APIs, in fan-out order:
   - first Button, InputText, Checkbox, RadioGroup, ToggleSwitch, Tag, Tooltip and InfoTooltip, LoadingSpinner, ProgressBar, Tabs, Alert, Card and Well, Breadcrumb, PageSelector, HypertextLink;
   - then BaseModal and TabbedModal, then Toaster, then Popover, and Dropdown last.

   Replace `Group`, `Spacing`, `Heading` and `Caret` with Tailwind by codemod. Map `Icon` glyphicons to Lucide with a lookup table.
5. **7e.** Page waves:
   1. Admin, Field Setup, Data Digest, Data Upload.
   2. Data Catalog and Data Quality Lab.
   3. AQT and the embedded query.
   4. Dashboard Builder.

   As each wave finishes, migrate callers to HeroUI's own API and delete the `ui/` wrappers and SCSS that nothing imports any more.
6. **7h.** Delete Bootstrap and SCSS, turn preflight on, ship dark mode.

**Keep custom, restyled on tokens:** HierarchicalSelector (consider React Aria `Tree`), the DatePicker shell, ColorBlock, DraggableItemList (React Aria drag and drop), UploadInput (React Aria `DropZone`), TextHighlighter.

**Heavy tables** use TanStack Table rendered inside HeroUI table markup.

## Before you call a screen done

- Run `frontend-design:frontend-design`'s own review criteria on the screen.
- Run `verify` at three widths in light mode, and dark mode after WP-7h.
- Take before and after screenshots and link them in the WP file.
- Check axe in Playwright.
- Check i18n with French strings.
- Check Amharic, plus the Ethiopian calendar where dates appear.
- Check keyboard-only operation of the main flow.
- Run the export path (`DashboardScreenshotApp`) for any dashboard-visible change. Exports must render the new fonts (`SharingUtil/canvas_util.js` inlines font files).
- Run `scripts/frontend/surface_report.mjs`. Importer counts for the modules you replaced must be zero before you delete them.
