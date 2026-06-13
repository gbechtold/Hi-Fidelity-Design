#!/usr/bin/env python3
"""IDML -> IR adapter (semantic tier).

InDesign Markup (.idml) is a ZIP of XML. This adapter extracts page items
(TextFrame / Rectangle / Polygon) with exact geometry, typography and colors,
and emits the common IR (../reference/ir-schema.json).

Usage:
    python3 idml_adapter.py --in design.idml --out design.ir.json [--probe]

--probe prints a ground-truth coverage summary (how much is exact vs. needs CV),
which is the recommended first step before a full audit.
"""
import argparse, json, math, re, sys, zipfile
import xml.etree.ElementTree as ET


def ln(tag):  # local-name without namespace
    return tag.split('}')[-1]


def find_all(root, name):
    return [e for e in root.iter() if ln(e.tag) == name]


def parse_transform(s):
    # "a b c d tx ty"
    try:
        a, b, c, d, tx, ty = [float(x) for x in s.split()]
        return (a, b, c, d, tx, ty)
    except Exception:
        return (1, 0, 0, 1, 0, 0)


def apply_tf(tf, x, y):
    a, b, c, d, tx, ty = tf
    return (a * x + c * y + tx, b * x + d * y + ty)


def frame_bounds(frame):
    """min/max of PathPointArray anchors, transformed by ItemTransform -> (x,y,w,h)."""
    tf = parse_transform(frame.get('ItemTransform', '1 0 0 1 0 0'))
    pts = []
    for pp in find_all(frame, 'PathPointType'):
        anchor = pp.get('Anchor')
        if not anchor:
            continue
        try:
            x, y = [float(v) for v in anchor.split()]
        except Exception:
            continue
        pts.append(apply_tf(tf, x, y))
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return {'x': round(min(xs), 2), 'y': round(min(ys), 2),
            'w': round(max(xs) - min(xs), 2), 'h': round(max(ys) - min(ys), 2)}


def build_color_table(zf):
    """Resources/Graphic.xml: named swatch -> #RRGGBB (best effort)."""
    table = {}
    try:
        root = ET.fromstring(zf.read('Resources/Graphic.xml'))
    except Exception:
        return table
    for col in find_all(root, 'Color'):
        self_id = col.get('Self')
        space = col.get('Space', 'RGB')
        val = col.get('ColorValue', '')
        hexv = colorvalue_to_hex(space, val)
        if self_id and hexv:
            table[self_id] = hexv
    return table


def colorvalue_to_hex(space, val):
    try:
        nums = [float(x) for x in val.split()]
    except Exception:
        return None
    if space == 'RGB' and len(nums) == 3:
        return '#%02X%02X%02X' % tuple(int(round(n)) for n in nums)
    if space == 'CMYK' and len(nums) == 4:
        c, m, y, k = [n / 100.0 for n in nums]
        r = 255 * (1 - c) * (1 - k)
        g = 255 * (1 - m) * (1 - k)
        b = 255 * (1 - y) * (1 - k)
        return '#%02X%02X%02X' % (int(round(r)), int(round(g)), int(round(b)))
    return None


def resolve_color(ref, table):
    """FillColor value -> (#RRGGBB | None, fidelity)."""
    if not ref:
        return None, None
    if '#' in ref:
        h = re.search(r'#([0-9A-Fa-f]{6})', ref)
        if h:
            return '#' + h.group(1).upper(), 'exact'
    m = re.search(r'R=(\d+)\s*G=(\d+)\s*B=(\d+)', ref)
    if m:
        return '#%02X%02X%02X' % tuple(int(x) for x in m.groups()), 'exact'
    if ref in table:
        return table[ref], 'exact'
    if 'None' in ref or 'Paper' in ref or 'Swatch' in ref:
        return None, 'exact'
    return None, 'heuristic'


def child_prop(elem, name):
    for props in find_all(elem, 'Properties'):
        for c in props:
            if ln(c.tag) == name:
                return (c.text or '').strip()
    return None


def story_typography(story_root, color_table):
    """First CharacterStyleRange of a story -> typography + text + color."""
    text_parts, typo, color, cfid = [], {}, None, None
    for csr in find_all(story_root, 'CharacterStyleRange'):
        if not typo:
            ps = csr.get('PointSize')
            if ps:
                typo['fontSize'] = round(float(ps), 2)
            if csr.get('Tracking'):
                typo['letterSpacing'] = float(csr.get('Tracking'))
            if csr.get('Capitalization'):
                typo['transform'] = csr.get('Capitalization')
            if csr.get('FontStyle'):
                typo['fontStyle'] = csr.get('FontStyle')
            lead = child_prop(csr, 'Leading')
            if lead and lead not in ('Auto',):
                try:
                    typo['lineHeight'] = round(float(lead), 2)
                except Exception:
                    pass
            font = child_prop(csr, 'AppliedFont')
            if font:
                typo['fontFamily'] = font
            color, cfid = resolve_color(csr.get('FillColor'), color_table)
        for content in find_all(csr, 'Content'):
            if content.text:
                text_parts.append(content.text)
    return typo, ' '.join(' '.join(text_parts).split()), color, cfid


def extract(idml_path):
    zf = zipfile.ZipFile(idml_path)
    color_table = build_color_table(zf)

    # stories by id
    stories = {}
    for n in zf.namelist():
        if n.startswith('Stories/Story_') and n.endswith('.xml'):
            sid = n.split('Story_')[1].rsplit('.xml', 1)[0]
            try:
                stories[sid] = ET.fromstring(zf.read(n))
            except Exception:
                pass

    elements = []
    canvas_w = canvas_h = None
    for n in zf.namelist():
        if not (n.startswith('Spreads/Spread_') and n.endswith('.xml')):
            continue
        root = ET.fromstring(zf.read(n))
        # page geometry -> canvas size
        for page in find_all(root, 'Page'):
            gb = page.get('GeometricBounds')
            if gb:
                try:
                    y0, x0, y1, x1 = [float(v) for v in gb.split()]
                    canvas_w = max(canvas_w or 0, x1 - x0)
                    canvas_h = (canvas_h or 0) + (y1 - y0)
                except Exception:
                    pass
        for tagname, etype in (('TextFrame', 'text'), ('Rectangle', 'box'), ('Polygon', 'box')):
            for fr in find_all(root, tagname):
                b = frame_bounds(fr)
                if not b or b['w'] < 1 or b['h'] < 1:
                    continue
                el = {'id': fr.get('Self'), 'type': etype, 'bounds': b,
                      'fidelity': {'bounds': 'exact'}}
                fill, ffid = resolve_color(fr.get('FillColor'), color_table)
                if fill:
                    el['color'] = {'fill': fill}
                    el['fidelity']['color'] = ffid
                if etype == 'text':
                    sid = fr.get('ParentStory')
                    if sid in stories:
                        typo, text, tcolor, cfid = story_typography(stories[sid], color_table)
                        if typo:
                            el['typography'] = typo
                            el['fidelity']['typography'] = 'exact'
                        if text:
                            el['name'] = text[:48]
                            el['text'] = text
                        if tcolor:
                            el['color'] = {'fill': tcolor}
                            el['fidelity']['color'] = cfid
                elements.append(el)

    return {
        'meta': {'source': 'idml', 'side': 'design', 'unit': 'pt',
                 'canvasWidth': round(canvas_w, 2) if canvas_w else None,
                 'canvasHeight': round(canvas_h, 2) if canvas_h else None},
        'elements': elements,
    }


def probe(ir):
    els = ir['elements']
    n = len(els)
    texts = [e for e in els if e['type'] == 'text']
    geo = sum(1 for e in els if e.get('fidelity', {}).get('bounds') == 'exact')
    typ = sum(1 for e in texts if e.get('fidelity', {}).get('typography') == 'exact')
    col = sum(1 for e in els if e.get('fidelity', {}).get('color') == 'exact')
    pct = lambda a, b: f'{(100*a/b):.0f}%' if b else 'n/a'
    print(f'--- Ground-truth probe: {ir["meta"]["source"]} ---')
    print(f'Canvas: {ir["meta"]["canvasWidth"]} x {ir["meta"]["canvasHeight"]} {ir["meta"]["unit"]}')
    print(f'Elements: {n}  (text: {len(texts)})')
    print(f'Exact geometry: {geo}/{n}  ({pct(geo, n)})')
    print(f'Exact typography: {typ}/{len(texts)}  ({pct(typ, len(texts))})')
    print(f'Exact color: {col}/{n}  ({pct(col, n)})')
    sized = [e for e in texts if e.get('typography', {}).get('fontSize')]
    if sized:
        sizes = sorted({e['typography']['fontSize'] for e in sized}, reverse=True)
        print(f'Distinct font sizes (pt): {", ".join(str(s) for s in sizes[:12])}')
    print(f'Verdict: {"HIGH — semantic source, extract exactly" if (geo/n if n else 0) > 0.8 else "MIXED — some CV fallback needed"}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='inp', required=True)
    ap.add_argument('--out', dest='out')
    ap.add_argument('--probe', action='store_true')
    a = ap.parse_args()
    ir = extract(a.inp)
    if a.out:
        with open(a.out, 'w', encoding='utf-8') as f:
            json.dump(ir, f, ensure_ascii=False, indent=2)
        print(f'IR written: {a.out}  ({len(ir["elements"])} elements)')
    if a.probe or not a.out:
        probe(ir)


if __name__ == '__main__':
    main()
