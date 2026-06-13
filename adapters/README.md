# Adapters

An adapter turns one source (design or implementation) into the common **IR**
(`../reference/ir-schema.json`). The core consumes only IR, so adding a tool = adding one
adapter; nothing else changes.

## Contract

- **Input**: a source artifact — a file path, a URL, or an API id.
- **Output**: a single IR JSON document on `--out`, valid against `ir-schema.json`.
- **Honesty**: every emitted value sets a `fidelity` flag (`exact | heuristic | manual`).
- **No cross-side logic**: an adapter must not normalize against the other side, diff, or
  assume a target width. It reports native units (`meta.unit`) and the canvas size; the
  core normalizes.

## Provided

| Adapter | Side | Tier | Status |
|---|---|---|---|
| `idml_adapter.py` | design | semantic | working (reference) |
| `dom_adapter.js` | implementation | semantic | working (Playwright) |
| `figma_adapter.py` | design | semantic | stub + spec |
| `pdf_adapter.py` | design | vector | stub + spec |
| `png_cv_adapter.py` | design/impl | raster | stub + spec |

## Add a new adapter — checklist

1. Read the source; collect elements (text / box / image).
2. For each: `id`, `type`, `bounds {x,y,w,h}` in native unit; plus `typography`,
   `color`, `text`, `radius` where available.
3. Set `meta.source`, `meta.side`, `meta.unit`, `meta.canvasWidth/Height`.
4. Set `fidelity` per property — be honest; estimated ⇒ `heuristic`/`manual`.
5. Emit IR JSON to `--out`. Optionally support `--probe` to print a coverage summary.
6. Register it in `bin/hifi`'s adapter table.

That is the entire integration surface.
