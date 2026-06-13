# Fidelity tiers

How much *exact* truth each source type exposes — this determines how much an adapter can
parse directly vs. must estimate (and flag `heuristic`/`manual`).

| Tier | Sources | What you get | Extraction method | Typical `fidelity` |
|---|---|---|---|---|
| **Semantic** | Figma REST API, IDML, Sketch, live DOM | element identity + exact geometry, type metrics, colors | parse structured data | `exact` |
| **Vector** | PDF, SVG | geometry + text runs + colors, but **no element identity/roles** | text/path extraction + grouping heuristics | `heuristic` for grouping, `exact` for values |
| **Raster** | PNG, JPG, screenshot | pixels only | CV: edge detection, color sampling, OCR for type size | `heuristic`/`manual` |

## Consequences

- The more semantic the source, the more is auto-extracted and the higher the confidence.
- A raster source needs a human-authored or CV-assisted reference and falls back to
  **spatial mapping** + **ghost-overlay** instead of a clean numeric property diff.
- Mixing tiers is fine: e.g. a semantic implementation (DOM) compared against a vector
  design (PDF) still yields exact implementation values and heuristic design targets — the
  report flags which side was estimated.

## Practical rule

Pick the most semantic export the design tool can give:

- InDesign → **IDML** (not just PDF/PNG).
- Figma → **REST API** (not an exported PNG).
- The implementation → the **DOM** (not a screenshot), whenever a URL exists.

Only drop to vector/raster when nothing better is available.
