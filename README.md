# Hi-Fidelity-Design

A Claude Code **skill** for high-fidelity *design ↔ implementation* audits. It answers
“how close is the build to the design?” with **numeric, per-element deltas** (geometry,
typography, color) plus a ghost-overlay — not a brittle pixel-by-pixel image diff.

> Compare **derived measurements**, not pixels. Design = target values, implementation =
> actual values (read from the DOM), diff = numeric with tolerances.

## Architecture — invariant core vs. swappable adapters

```
SOURCE adapters ─┐                              ┌─ TARGET adapters
 idml  figma     │   ┌────────────────────┐     │  dom (Playwright)
 pdf   png-cv ───┼──▶│  COMMON IR (schema) │◀────┼─ static-html  screenshot
 sketch          │   └────────────────────┘     │
                 │   INVARIANT CORE:  normalize → map → diff → score → report + overlay
```

Add a tool = write **one adapter** that emits the common IR
([`reference/ir-schema.json`](reference/ir-schema.json)). The core never changes. Full
rationale in [`reference/architecture.md`](reference/architecture.md); source fidelity
tiers in [`reference/fidelity-tiers.md`](reference/fidelity-tiers.md).

## Install (as a Claude Code skill)

```bash
git clone https://github.com/gbechtold/Hi-Fidelity-Design.git \
  ~/.claude/skills/Hi-Fidelity-Design
```

Then in Claude Code the skill is available by name; or run the CLI directly.

## Quick start

```bash
# 0) Probe how much exact truth a design source gives (recommended first)
python3 adapters/idml_adapter.py --in design.idml --out design.ir.json --probe

# 1) Extract implementation IR from the live page
node adapters/dom_adapter.js --url https://staging.example.com/ \
     --selectors ".hero__title,.cta" --width 1920 --out impl.ir.json

# 2) Map design ↔ impl (examples/indie-wandern.mapping.json) and diff
python3 bin/hifi diff design.ir.json impl.ir.json \
     --map mapping.json --out audit/
```

`audit/REPORT.md` is sorted by largest delta; exit code is non-zero if any element fails.

## Adapters

| Adapter | Side | Tier | Status |
|---|---|---|---|
| `idml_adapter.py` | design | semantic | ✅ working |
| `dom_adapter.js` (Playwright) | implementation | semantic | ✅ working |
| `figma_adapter.py` | design | semantic | spec/stub |
| `pdf_adapter.py` | design | vector | spec/stub |
| `png_cv_adapter.py` | design / impl | raster | spec/stub |

## Tolerances

- Geometry ✅ ±2 % · ⚠️ 2–5 % · ❌ >5 %
- Type size ✅ ±1 px · ⚠️ 1–3 px · ❌ >3 px
- Color ✅ ΔE<2 · ⚠️ 2–5 · ❌ >5 (CIEDE2000)

Override per project in `mapping.json → "tolerances"`.

## Example output

Real audit (InDesign IDML design vs. live WordPress build), hero headline:

```
Design: idml (1920pt) · Impl: dom (1920px) · scale ×1.0
| Element                  | Prop     | Design  | Impl    | Δ        |    |
| wandern macht glücklich  | fontSize | 225.0   | 208     | -17.0px  | ❌ |
| wandern macht glücklich  | color    | #F5EFE7 | #FFFFFF | ΔE 5.25  | ❌ |
```

## Requirements

- Core (IDML + diff): **Python 3 standard library only**.
- DOM adapter: `npm i playwright`.
- Optional adapters: see `requirements.txt`.

## License

MIT — see [LICENSE](LICENSE).
