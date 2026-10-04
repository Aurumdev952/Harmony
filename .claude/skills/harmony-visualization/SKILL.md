---
name: harmony-visualization
description: Harmony's charts and maps migration, from @vx 0.0.195, Plotly 1.22, the d3 v3 global and react-map-gl 6 with Mapbox to visx 4, d3 modules and MapLibre GL JS 6 via @vis.gl/react-maplibre, themed by the design tokens. Use for anything under web/client/components/visualizations, components/ui/visualizations or components/QueryResult, and for chart export output. Pair it with dataviz for chart design and the vendored maplibre-v6-migration and maplibre-source-wiring skills for maps.
---

# Harmony visualizations

Load these first:
- `dataviz`: chart form, colour formulas, marks, interaction.
- `maplibre-v6-migration` and `maplibre-source-wiring`: map work.
- `harmony-design-system`: tokens and typography.

## Inventory

| Chart | Renderer today | Target |
|---|---|---|
| BarGraph, Histogram, BoxPlot, BumpChart, EpiCurve, NumberTrend, PieChart, ui LineGraph | @vx 0.0.195 (27 files) | visx 4 or later (React 19 peer support starts at 4) |
| product LineGraph, BubbleChart, HeatTiles | Plotly 1.22 global, loaded by `withScriptLoader` and `grid_dashboard.html` | visx |
| Sunburst, ExpandoTree | d3 v3 global (`window.d3.layout`, `d3.svg`) | `d3-hierarchy` with visx |
| MapCore and MapViz (46 files) | react-map-gl 6 and mapbox-gl 2.4, token from `__JSON_FROM_BACKEND` | `@vis.gl/react-maplibre` (or `react-map-gl/maplibre`) with `maplibre-gl` 6 |
| Table viz | react-window | keep, restyle |

## Rules

- **Prove before replacing.** Before replacing a renderer, add a golden visual test (Playwright screenshot with a fixed dataset) for that chart type. The replacement must match in data, scales, ordering and labels. Styling may change only through tokens.
- **`@vx` to `@visx` is a rename first.** Run the codemod, prove the visuals match, then upgrade to visx 4 in a separate unit.
- **MapLibre 6.**
  - It has no default export, so never write `import maplibregl from 'maplibre-gl'`.
  - It ships ESM only.
  - `setWorkerUrl()` is needed with bundlers.
  - `MapDataEvent` is split into `MapSourceDataEvent` and `MapStyleDataEvent`.
  - Remove the Mapbox token and its billing. Tiles come from a self-hosted style or an open provider configured per deployment, and never from a hard-coded third party (SEC-10).
- **Theme from tokens.** Chart theme objects (`LABEL_FONT`, `titleFontFamily`, `textFont()`) read tokens:
  - `--font-numeric` for axes, ticks, values and tooltips;
  - `--font-sans` for titles and legends;
  - series colours from the categorical palette in `tokens.css`, through the generated `Colors.ts`.
- **Exports render the same fonts.** `components/common/SharingUtil/canvas_util.js` inlines font files for PNG and PDF. Give it the new WOFF2 files, and check exports through the WP-1h renderer.
- **Performance.**
  - Large series must not re-render on hover. Memoise scales and paths.
  - Map layers above about 50,000 features go to deck.gl only with a measured need.
- **Accessibility.** Each chart has a text summary or a data-table alternative reachable by keyboard. Colour is never the only channel. Use pattern or label fallbacks, following the `dataviz` guidance.

## Checks

```bash
pnpm test components/visualizations
pnpm e2e --grep @viz
```

Also run `verify` on AQT with each visualization type and on one dashboard per chart type. Record bundle size for the dashboard entry before and after (Plotly removal should cut about 1.9 MB).
