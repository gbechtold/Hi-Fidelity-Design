#!/usr/bin/env python3
"""pdf -> IR adapter (STUB + spec).

Not yet implemented. See ../reference/fidelity-tiers.md for the extraction strategy.
Implement extract() to emit IR per ../reference/ir-schema.json, set honest
fidelity flags, then it plugs into bin/hifi unchanged.
"""
import sys
SPEC = {
  "figma_adapter": "Figma REST API: GET /v1/files/:key -> node tree. absoluteBoundingBox -> bounds; style.fontSize/lineHeightPx/letterSpacing -> typography; fills[0].color -> color. Tier: semantic (fidelity=exact). Auto-mapping by layer name possible.",
  "pdf_adapter": "PDF (vector): pdfminer.six for text runs (chars -> font size, position) + color; group runs into blocks (heuristic). Tier: vector (fidelity: values exact, grouping heuristic).",
  "png_cv_adapter": "Raster: Pillow + OpenCV. Edge detection for boxes, dominant-color sampling for fills, OCR (tesseract) cap-height -> font size. Tier: raster (fidelity=heuristic/manual). Needs spatial mapping + reference assist.",
}
print("STUB pdf_adapter — not implemented yet.\n\nStrategy:\n  " + SPEC["pdf_adapter"], file=sys.stderr)
sys.exit(3)
