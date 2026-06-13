---
name: Hi-Fidelity-Design
description: >-
  Compare a design source (Figma, InDesign/IDML, PDF, PNG, Sketch) against a live
  implementation (DOM via Playwright, static HTML, screenshot) and produce a numeric,
  per-element fidelity diff plus a ghost-overlay — not a brittle pixel-by-pixel image
  diff. Use when the user wants to know "how close is the build to the design", a
  pixel-perfect audit, design-QA, or a design-vs-staging comparison. Architecture:
  one invariant core (normalize → map → diff → score → overlay) + swappable
  source adapters that all emit a common Intermediate Representation (IR).
---

# Hi-Fidelity-Design

Measure how faithfully an implementation reproduces a design — objectively.

## The core idea

Do **not** diff two images RGB-by-RGB. Responsive layout, font rendering, anti-aliasing
and photo content make that 100 % noise. Instead compare **derived measurements**:

- **Design = target values** (what the designer meant: this heading is 96 pt, this gap is
  80 px, this red is `#CF3329`).
- **Implementation = actual values** (what the browser renders, read from the DOM).
- **Diff = numeric, per property, with tolerances** — not per pixel.

Every source is reduced to one **Intermediate Representation (IR)** (see
`reference/ir-schema.json`). The comparison engine only ever sees IR, so it is
source-agnostic.

## Architecture: invariant core vs. swappable adapters

```
SOURCE adapters ─┐                              ┌─ TARGET adapters
 idml  figma     │   ┌────────────────────┐     │  dom (Playwright)
 pdf   png-cv ───┼──▶│  COMMON IR (schema) │◀────┼─ static-html  screenshot
 sketch          │   └────────────────────┘     │
                 │            │                  │
                 │   INVARIANT CORE (never changes per source):
                 │   normalize → map → diff → score → report + ghost-overlay
```

Add a new design tool or a new implementation target by writing **one adapter** that
emits IR. The core, tolerances, ΔE color logic, anchoring and overlay are reused
unchanged. See `reference/architecture.md`.

## Fidelity tiers

Sources differ only in how much structured truth they expose — this decides how much is
auto-extracted vs. estimated. See `reference/fidelity-tiers.md`.

| Source | Truth | Extraction | Manual effort |
|---|---|---|---|
| Figma API, IDML, DOM | exact | parse | little / none |
| PDF (vector) | geometry+text, no semantics | extract + heuristics | medium |
| PNG/JPG (raster) | pixels only | CV + OCR | high (reference JSON) |

Each extracted value carries a `fidelity` flag (`exact | heuristic | manual`) so the
report never claims "pixel perfect" where a value was actually estimated.

## Workflow

1. **Extract design IR** — `bin/hifi extract --adapter <idml|figma|pdf|png> --in <src> --out design.ir.json`
2. **Extract implementation IR** — `bin/hifi extract --adapter dom --url <url> --out impl.ir.json`
   (DOM adapter shells out to Playwright; supports HTTP basic-auth + viewport)
3. **Map** — author `mapping.json`: design element id ↔ implementation selector
   (identity-mapping when ≥1 side is semantic; spatial-mapping when both are raster).
4. **Diff & score** — `bin/hifi diff design.ir.json impl.ir.json --map mapping.json --out audit/`
   → `audit/diff.json` + `audit/REPORT.md`, sorted by largest delta, with pass/warn/fail.
5. **Overlay (optional)** — ghost the design comp over a live screenshot for the human
   gut-check the numbers can't give (optical alignment, curves, texture).
6. **Iterate** — fix CSS → re-run → deltas shrink → converge. Done = 0 fail, warns
   consciously accepted.

## Checks — declarative rule set (per element / role)

Beyond the pair-diff, `bin/hifi check` evaluates a **rule set**: each check is
`{ target, dim, op, expected, tol }`. Dimensions:

- `scalar` — numeric (fontSize, width, `lineHeightRatio`…) → delta + tolerance
- `categorical` — fontFamily/fontStyle/transform → eq/contains (+ optional `realFaceExists` lint)
- `color` — CIEDE2000 ΔE
- `relational` — ratio between two elements (`a.metric / b.metric` ∈ band) — scale-robust
- `structural` / `behavioral` — shape / state-on-interaction → reported as `pending` (needs a
  shape-descriptor resp. interaction-capture evaluator; honest measurability)

`expected` comes from the design IR (`designRef`) or a literal/band. Rules attach per element
or per **role** (reuse a bundle of checks across many elements). Run:

```bash
python3 bin/hifi check design.ir.json impl.ir.json --rules rules.json --out checks/
```
→ `checks/CHECKS.md` sorted by severity; each row carries its verdict (✅/⚠️/❌/🔌-pending).
Example rule set: `examples/indie-wandern.hero.checks.json`.

## Tolerances (per measurement class)

- Geometry: ✅ ±2 % · ⚠️ 2–5 % · ❌ >5 %
- Type size: ✅ ±1 px · ⚠️ 1–3 px · ❌ >3 px
- Color: ✅ ΔE<2 · ⚠️ 2–5 · ❌ >5  (CIEDE2000)

Override per project in `mapping.json → "tolerances"`.

## When NOT to use

- Pixel-exact visual regression between two builds → use Percy / Chromatic / Playwright
  `toHaveScreenshot`. This skill measures **design ↔ implementation**, not build ↔ build.
- A single quick screenshot → just use Playwright inline.

## Quick start (ground-truth probe)

Before a full audit, check how much exact truth a design source gives:

```
python3 adapters/idml_adapter.py --in design.idml --out /tmp/design.ir.json --probe
```

The `--probe` flag prints a coverage summary (elements found, % with exact
geometry / type / color) so you know up front how much will be exact vs. CV-estimated.
