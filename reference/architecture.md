# Architecture — invariant core vs. swappable adapters

## The two seams

The workflow varies only at its two edges. The middle is constant.

```
  SOURCE (design)            INVARIANT CORE                 TARGET (implementation)
  ┌──────────────┐                                          ┌────────────────────┐
  │ idml_adapter │──┐    ┌───────────────────────┐      ┌───│ dom_adapter        │
  │ figma_adapter│──┤    │  ③ normalize          │      │   │ (Playwright)       │
  │ pdf_adapter  │──┼──▶ │  ④ map                │ ◀────┼───│ static_html_adapter│
  │ png_cv_adapter│─┘    │  ⑤ diff + score       │      │   │ screenshot_adapter │
  └──────────────┘   IR  │  ⑥ report + overlay   │  IR  │   └────────────────────┘
                         └───────────────────────┘
```

Both edges speak the same **IR** (`ir-schema.json`). The core never knows or cares which
adapter produced the IR. That is the whole trick to generalization.

## What is invariant (the core — never rewritten per project/source)

- **normalize**: native unit → common px via `scale = targetWidth / canvasWidth`;
  colors → CIELAB for ΔE; Y-axis → anchor-relative (a scrolling page vs. a static comp
  cannot be compared on absolute Y — pick a shared anchor, e.g. logo top-left).
- **map**: resolve which design element corresponds to which implementation element.
- **diff + score**: per property `Δ`, classified by tolerance into pass/warn/fail.
- **report + overlay**: numeric table (machine-diffable JSON + human Markdown) and the
  ghost overlay (design comp at 50 % over the live screenshot).

## What is swappable (adapters — one per source/target type)

An adapter is any program that reads a source and writes a valid IR JSON. Contract:

- Input: a source artifact (file, URL, API id).
- Output: IR conforming to `ir-schema.json`, with honest `fidelity` flags.
- It does **not** diff, normalize, or know about the other side.

See `adapters/README.md` for the contract and a checklist to add one.

## The mapping seam (the one thing that does not fully auto-generalize)

"Which design element == which implementation element?" has two modes:

- **Identity mapping** — used when ≥1 side is semantic (Figma layer names, IDML frame
  names, CSS selectors / `data-*`). A `mapping.json` of `{designId: selector}`; can be
  auto-derived when names line up.
- **Spatial mapping** — used when *both* sides are raster. Match by bounding-box overlap
  after anchor registration. Fuzzy; lower confidence.

## Fidelity honesty

Every value carries `fidelity: exact | heuristic | manual`. The report aggregates it, so
a result is never presented as "pixel perfect" when, e.g., a PNG source had its font size
OCR-estimated. Truth tiers are documented in `fidelity-tiers.md`.

## Why this generalizes (PNG+IDML today, PDF+PNG or Figma+HTML tomorrow)

- **Figma + HTML** → both semantic → fully automatable, auto-mapping by name. Easiest.
- **IDML + DOM** → both semantic → exact both sides (the reference implementation here).
- **PDF + PNG** → both non-semantic → numeric DOM diff impossible; fall back to
  CV measurement + ghost-overlay, spatial mapping. Hardest, lowest fidelity — and the
  report says so.

The effort shifts with source fidelity; the architecture does not change.
