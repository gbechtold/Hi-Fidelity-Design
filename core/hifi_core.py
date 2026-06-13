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


# =========================================================================
#  CHECKS-ENGINE — deklaratives Regelset pro Element/Rolle.
#  Dimensionen: scalar | categorical | color | relational | structural | behavioral
#  Jede Regel deklariert ihre Messbarkeit; structural/behavioral = needs-modality.
# =========================================================================

_NUMERIC_GEO = {'fontSize', 'lineHeight', 'letterSpacing', 'width', 'height', 'x', 'y'}


def metric_value(el, metric):
    """Holt einen Metrik-Wert aus einem IR-Element. Liefert (wert, ist_numerisch_geo)."""
    if el is None:
        return None, False
    t = el.get('typography', {}) or {}
    b = el.get('bounds', {}) or {}
    col = el.get('color', {}) or {}
    if metric in ('fontSize', 'lineHeight', 'letterSpacing', 'weight', 'fontFamily', 'fontStyle', 'transform'):
        v = t.get(metric)
        try:
            v = float(v)
        except (TypeError, ValueError):
            pass
        return v, metric in _NUMERIC_GEO
    if metric in ('width', 'height', 'x', 'y'):
        return b.get({'width': 'w', 'height': 'h', 'x': 'x', 'y': 'y'}[metric]), True
    if metric == 'color':
        return col.get('fill'), False
    if metric == 'lineHeightRatio':           # abgeleitet, einheitenlos → kein Scale
        fs = t.get('fontSize'); lh = t.get('lineHeight')
        try:
            return (float(lh) / float(fs)) if (fs and lh) else None, False
        except (TypeError, ValueError, ZeroDivisionError):
            return None, False
    return None, False


def eval_checks(design_ir, impl_ir, rules):
    tol_def = {'scalar': [2, 5], 'color': [2, 5], 'ratio': [0.05, 0.12]}
    dw = design_ir['meta'].get('canvasWidth'); iw = impl_ir['meta'].get('canvasWidth')
    scale = rules.get('scale')
    if scale in (None, 'auto'):
        scale = (iw / dw) if (dw and iw) else 1.0
    didx = index(design_ir); iidx_id, _ = index(impl_ir)

    def impl_el(sel): return iidx_id.get(sel)
    def design_el(ref): return find_design(didx, ref) if ref else None

    out = []
    for c in rules.get('checks', []):
        dim = c.get('dim')
        row = {'id': c.get('id', dim), 'dim': dim, 'target': c.get('target'), 'verdict': 'pass', 'detail': ''}

        if dim in ('structural', 'behavioral'):
            row['verdict'] = 'pending'
            row['detail'] = c.get('note', 'needs-modality: ' + ('Shape-Deskriptor' if dim == 'structural' else 'Interaktions-Capture'))
            out.append(row); continue

        # Top-Level-Target nur für element-bezogene Dims (relational nutzt a/b)
        if dim in ('scalar', 'categorical', 'color'):
            im = impl_el(c.get('target'))
            if im is None or im.get('missing'):
                row['verdict'] = 'fail'; row['detail'] = 'impl-Selector nicht gefunden'; out.append(row); continue

        if dim == 'scalar':
            metric = c['metric']
            iv, is_geo = metric_value(im, metric)
            if 'expected' in c:
                ev = c['expected']
            else:
                dv, dgeo = metric_value(design_el(c.get('designRef')), metric)
                ev = (dv * scale) if (dv is not None and is_geo) else dv
            if iv is None or ev is None:
                row['verdict'] = 'fail'; row['detail'] = f'{metric}: Wert fehlt (design={ev}, impl={iv})'
            else:
                tol = c.get('tol', tol_def['scalar'])
                delta = iv - ev
                row['verdict'] = verdict(delta, tol[0], tol[1])
                row['detail'] = f'{metric}: soll {round(ev,2)} · ist {round(iv,2)} · Δ {delta:+.2f}'

        elif dim == 'color':
            iv, _ = metric_value(im, 'color')
            ev = c.get('expected') or metric_value(design_el(c.get('designRef')), 'color')[0]
            de = delta_e(ev, iv)
            tol = c.get('tol', tol_def['color'])
            row['verdict'] = 'fail' if de is None else verdict(de, tol[0], tol[1])
            row['detail'] = f'Farbe: soll {ev} · ist {iv} · ΔE {de}'

        elif dim == 'categorical':
            iv, _ = metric_value(im, c['metric'])
            ev = c.get('expected')
            op = c.get('op', 'eq')
            ivs = str(iv).lower(); evs = str(ev).lower()
            ok = (evs in ivs) if op == 'contains' else (ivs == evs)
            row['verdict'] = 'pass' if ok else 'fail'
            row['detail'] = f'{c["metric"]}: soll {op} "{ev}" · ist "{iv}"'
            if c.get('lint') == 'realFaceExists' and c.get('realFaces') is not None:
                fam = (metric_value(im, 'fontFamily')[0] or '').split(',')[0].strip().strip('"').lower()
                style = (metric_value(im, 'fontStyle')[0] or 'normal')
                has = any(f.lower() == fam and s == style for f, s in c['realFaces'])
                if not has:
                    row['verdict'] = 'warn' if row['verdict'] == 'pass' else row['verdict']
                    row['detail'] += f' · ⚠ kein echter Schnitt ({fam} {style}) → faux'

        elif dim == 'relational':
            a = c['a']; b = c['b']
            av, ageo = metric_value(impl_el(a['target']) or design_el(a.get('designRef')), a['metric'])
            bv, bgeo = metric_value(impl_el(b['target']) or design_el(b.get('designRef')), b['metric'])
            if av is None or bv is None or not bv:
                row['verdict'] = 'fail'; row['detail'] = f'relational: Wert fehlt (a={av}, b={bv})'
            else:
                ratio = av / bv
                lo, hi = c.get('expected', [0, 99])
                row['verdict'] = 'pass' if lo <= ratio <= hi else ('warn' if lo * .8 <= ratio <= hi * 1.2 else 'fail')
                row['detail'] = f'{a["metric"]}/{b["metric"]} = {ratio:.2f} · soll ∈ [{lo},{hi}]'
        else:
            row['verdict'] = 'pending'; row['detail'] = f'unbekannte dim: {dim}'
        out.append(row)
    return {'scale': round(scale, 4), 'checks': out}


def report_checks_md(result, design_ir, impl_ir):
    ic = {'pass': '✅', 'warn': '⚠️', 'fail': '❌', 'pending': '🔌'}
    counts = {}
    for r in result['checks']:
        counts[r['verdict']] = counts.get(r['verdict'], 0) + 1
    head = ' · '.join(f"{counts.get(k,0)} {k}" for k in ['pass', 'warn', 'fail', 'pending'])
    lines = ['# Hi-Fidelity-Design — Checks', '',
             f"Design `{design_ir['meta']['source']}` ({design_ir['meta'].get('canvasWidth')}{design_ir['meta']['unit']}) · "
             f"Impl `{impl_ir['meta']['source']}` ({impl_ir['meta'].get('canvasWidth')}px) · scale ×{result['scale']}",
             '', f'**{head}**', '', '| | Check | Dim | Detail |', '|---|---|---|---|']
    sev = {'fail': 0, 'warn': 1, 'pending': 2, 'pass': 3}
    for r in sorted(result['checks'], key=lambda x: sev.get(x['verdict'], 9)):
        lines.append(f"| {ic.get(r['verdict'],'?')} | {r['id']} | {r['dim']} | {r['detail']} |")
    return '\n'.join(lines) + '\n'


def run_checks(design_path, impl_path, rules_path, out_dir):
    design_ir = json.load(open(design_path, encoding='utf-8'))
    impl_ir = json.load(open(impl_path, encoding='utf-8'))
    rules = json.load(open(rules_path, encoding='utf-8'))
    result = eval_checks(design_ir, impl_ir, rules)
    os.makedirs(out_dir, exist_ok=True)
    json.dump(result, open(os.path.join(out_dir, 'checks.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    md = report_checks_md(result, design_ir, impl_ir)
    open(os.path.join(out_dir, 'CHECKS.md'), 'w', encoding='utf-8').write(md)
    return result, md


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
