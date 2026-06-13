#!/usr/bin/env python3
"""Invariant core: normalize -> map -> diff -> score -> report.

Source-agnostic. Consumes two IR documents (design + implementation) and a
mapping.json, emits diff.json + REPORT.md. Knows nothing about IDML/Figma/DOM.
"""
import json, math, os


# ---------- color: hex -> Lab -> CIEDE2000 ----------
def _hex_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_lab(rgb):
    def f(c):
        c /= 255.0
        c = ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92
        return c * 100
    r, g, b = [f(c) for c in rgb]
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 95.047
    y = (r * 0.2126 + g * 0.7152 + b * 0.0722) / 100.0
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 108.883
    def g2(t):
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t + 16 / 116)
    fx, fy, fz = g2(x), g2(y), g2(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(h1, h2):
    """CIEDE2000 between two #RRGGBB strings."""
    if not h1 or not h2:
        return None
    L1, a1, b1 = _rgb_lab(_hex_rgb(h1))
    L2, a2, b2 = _rgb_lab(_hex_rgb(h2))
    avg_L = (L1 + L2) / 2
    C1 = math.hypot(a1, b1); C2 = math.hypot(a2, b2)
    avg_C = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(avg_C ** 7 / (avg_C ** 7 + 25 ** 7))) if avg_C else 0
    a1p, a2p = a1 * (1 + G), a2 * (1 + G)
    C1p = math.hypot(a1p, b1); C2p = math.hypot(a2p, b2)
    avg_Cp = (C1p + C2p) / 2
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360
    dLp = L2 - L1; dCp = C2p - C1p
    dhp = h2p - h1p
    if abs(dhp) > 180:
        dhp -= 360 * (1 if dhp > 0 else -1)
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp) / 2)
    avg_hp = (h1p + h2p + (360 if abs(h1p - h2p) > 180 else 0)) / 2
    T = (1 - 0.17 * math.cos(math.radians(avg_hp - 30)) + 0.24 * math.cos(math.radians(2 * avg_hp))
         + 0.32 * math.cos(math.radians(3 * avg_hp + 6)) - 0.20 * math.cos(math.radians(4 * avg_hp - 63)))
    Sl = 1 + (0.015 * (avg_L - 50) ** 2) / math.sqrt(20 + (avg_L - 50) ** 2)
    Sc = 1 + 0.045 * avg_Cp
    Sh = 1 + 0.015 * avg_Cp * T
    dTheta = 30 * math.exp(-(((avg_hp - 275) / 25) ** 2))
    Rc = 2 * math.sqrt(avg_Cp ** 7 / (avg_Cp ** 7 + 25 ** 7))
    Rt = -Rc * math.sin(math.radians(2 * dTheta))
    return round(math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2
                           + Rt * (dCp / Sc) * (dHp / Sh)), 2)


# ---------- lookup helpers ----------
def index(ir):
    by_id = {e['id']: e for e in ir['elements']}
    by_text = {}
    for e in ir['elements']:
        t = (e.get('text') or e.get('name') or '').strip().lower()
        if t:
            by_text.setdefault(t, e)
    return by_id, by_text


def find_design(ir_idx, key):
    by_id, by_text = ir_idx
    if key in by_id:
        return by_id[key]
    k = key.strip().lower()
    if k in by_text:
        return by_text[k]
    for t, e in by_text.items():           # contains-match fallback
        if k and k in t:
            return e
    return None


# ---------- tolerances ----------
DEFAULT_TOL = {'geometry_pct': [2, 5], 'fontsize_px': [1, 3], 'deltaE': [2, 5]}


def verdict(delta, warn, fail):
    a = abs(delta)
    return 'pass' if a <= warn else ('warn' if a <= fail else 'fail')


# ---------- diff ----------
def diff(design_ir, impl_ir, mapping):
    tol = {**DEFAULT_TOL, **mapping.get('tolerances', {})}
    dw = design_ir['meta'].get('canvasWidth')
    iw = impl_ir['meta'].get('canvasWidth')
    scale = mapping.get('scale')
    if scale in (None, 'auto'):
        scale = (iw / dw) if (dw and iw) else 1.0
    didx = index(design_ir)
    iidx_by_id, _ = index(impl_ir)

    rows = []
    for pair in mapping.get('pairs', []):
        d = find_design(didx, pair['design'])
        im = iidx_by_id.get(pair['impl'])
        row = {'design': pair['design'], 'impl': pair['impl'], 'props': {}, 'worst': 'pass'}
        if not d or not im or im.get('missing'):
            row['worst'] = 'fail'
            row['error'] = ('design not found' if not d else 'impl selector not found')
            rows.append(row); continue

        def rec(name, dval, ival, kind):
            if dval is None or ival is None:
                return
            if kind == 'pct':
                base = dval if dval else 1
                delta = (ival - dval) / base * 100
                v = verdict(delta, *tol['geometry_pct'])
                row['props'][name] = {'design': round(dval, 1), 'impl': round(ival, 1), 'deltaPct': round(delta, 1), 'verdict': v}
            elif kind == 'px':
                delta = ival - dval
                v = verdict(delta, *tol['fontsize_px'])
                row['props'][name] = {'design': round(dval, 1), 'impl': round(ival, 1), 'deltaPx': round(delta, 1), 'verdict': v}
            elif kind == 'color':
                de = delta_e(dval, ival)
                v = 'pass' if de is None else verdict(de, *tol['deltaE'])
                row['props'][name] = {'design': dval, 'impl': ival, 'deltaE': de, 'verdict': v}
            order = {'pass': 0, 'warn': 1, 'fail': 2}
            if order[row['props'][name]['verdict']] > order[row['worst']]:
                row['worst'] = row['props'][name]['verdict']

        # geometry (design pt -> px via scale); width/height are scale-independent of anchoring
        db, ib = d.get('bounds', {}), im.get('bounds', {})
        rec('width', db.get('w', 0) * scale, ib.get('w'), 'pct')
        rec('height', db.get('h', 0) * scale, ib.get('h'), 'pct')
        # typography
        dt, it = d.get('typography', {}), im.get('typography', {})
        if dt.get('fontSize') and it.get('fontSize'):
            rec('fontSize', dt['fontSize'] * scale, it['fontSize'], 'px')
        # color
        dc, ic = (d.get('color') or {}).get('fill'), (im.get('color') or {}).get('fill')
        rec('color', dc, ic, 'color')
        rows.append(row)
    return {'scale': round(scale, 4), 'rows': rows}


def report_md(result, design_ir, impl_ir):
    counts = {'pass': 0, 'warn': 0, 'fail': 0}
    for r in result['rows']:
        counts[r['worst']] += 1
    lines = ['# Hi-Fidelity-Design — Audit', '',
             f"Design: `{design_ir['meta']['source']}` ({design_ir['meta'].get('canvasWidth')}{design_ir['meta']['unit']}) · "
             f"Impl: `{impl_ir['meta']['source']}` ({impl_ir['meta'].get('canvasWidth')}px) · scale ×{result['scale']}",
             '', f"**{counts['pass']} pass · {counts['warn']} warn · {counts['fail']} fail**", '',
             '| Element | Prop | Design | Impl | Δ | |', '|---|---|---|---|---|---|']
    sev = {'fail': 0, 'warn': 1, 'pass': 2}
    icon = {'pass': '✅', 'warn': '⚠️', 'fail': '❌'}
    for r in sorted(result['rows'], key=lambda x: sev[x['worst']]):
        if r.get('error'):
            lines.append(f"| `{r['design']}` → `{r['impl']}` | — | — | — | — | ❌ {r['error']} |")
            continue
        for prop, p in r['props'].items():
            d = p.get('deltaPct'); dpx = p.get('deltaPx'); de = p.get('deltaE')
            dstr = (f"{d:+.1f}%" if d is not None else f"{dpx:+.1f}px" if dpx is not None else f"ΔE {de}")
            lines.append(f"| {r['design'][:28]} | {prop} | {p['design']} | {p['impl']} | {dstr} | {icon[p['verdict']]} |")
    return '\n'.join(lines) + '\n'


CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'


def label_for(i):
    return CIRCLED[i] if i < len(CIRCLED) else f'[{i+1}]'


def _short_caption(props):
    """Compact per-element caption for the marker."""
    bits = []
    for name, p in props.items():
        if p['verdict'] == 'pass':
            continue
        if 'deltaPx' in p:
            bits.append(f"{name} {p['deltaPx']:+.0f}px")
        elif 'deltaE' in p and p['deltaE'] is not None:
            bits.append(f"ΔE{p['deltaE']:.1f}")
        elif 'deltaPct' in p:
            bits.append(f"{name} {p['deltaPct']:+.0f}%")
    return ' · '.join(bits[:3])


def build_boxes(result, design_ir, impl_ir):
    """Marker boxes for both sides, sharing the same label index. Returns (design_boxes, impl_boxes)."""
    didx_id, didx_txt = index(design_ir)
    iidx_id, _ = index(impl_ir)
    dboxes, iboxes = [], []
    for i, r in enumerate(result['rows']):
        lab = label_for(i)
        cap = _short_caption(r.get('props', {})) or r.get('error', '')
        d = find_design((didx_id, didx_txt), r['design'])
        im = iidx_id.get(r['impl'])
        if d and d.get('bounds'):
            b = d['bounds']
            dboxes.append({'x': b['x'], 'y': b['y'], 'w': b['w'], 'h': b['h'],
                           'label': lab, 'verdict': r['worst'], 'caption': cap})
        if im and im.get('bounds') and not im.get('missing'):
            b = im['bounds']
            iboxes.append({'x': b['x'], 'y': b['y'], 'w': b['w'], 'h': b['h'],
                           'label': lab, 'verdict': r['worst'], 'caption': cap})
    return dboxes, iboxes


def todos_from_diff(result):
    """Human, actionable update todos derived from warn/fail props."""
    todos = []
    for i, r in enumerate(result['rows']):
        lab = label_for(i)
        name = r['design']
        if r.get('error'):
            todos.append(f"{lab} {name}: {r['error']} — Mapping/Selector prüfen")
            continue
        for prop, p in r.get('props', {}).items():
            if p['verdict'] == 'pass':
                continue
            sev = '❌' if p['verdict'] == 'fail' else '⚠️'
            if prop == 'color':
                todos.append(f"{lab} {sev} {name}: Farbe {p['impl']} → {p['design']} (ΔE {p['deltaE']})")
            elif prop == 'fontSize':
                todos.append(f"{lab} {sev} {name}: font-size {p['impl']}px → {p['design']}px ({p['deltaPx']:+.0f})")
            elif prop in ('width', 'height'):
                todos.append(f"{lab} {sev} {name}: {prop} {p['impl']}px vs Soll {p['design']}px ({p['deltaPct']:+.0f}%)")
    return todos


def run_diff(design_path, impl_path, mapping_path, out_dir):
    design_ir = json.load(open(design_path, encoding='utf-8'))
    impl_ir = json.load(open(impl_path, encoding='utf-8'))
    mapping = json.load(open(mapping_path, encoding='utf-8'))
    result = diff(design_ir, impl_ir, mapping)
    os.makedirs(out_dir, exist_ok=True)
    json.dump(result, open(os.path.join(out_dir, 'diff.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    md = report_md(result, design_ir, impl_ir)
    open(os.path.join(out_dir, 'REPORT.md'), 'w', encoding='utf-8').write(md)
    return result, md
