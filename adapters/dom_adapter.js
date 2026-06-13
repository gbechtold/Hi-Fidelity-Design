#!/usr/bin/env node
/* DOM -> IR adapter (semantic tier, implementation side).
 * Reads a live page with Playwright and emits IR for a list of selectors.
 *
 * Usage:
 *   node dom_adapter.js --url https://… --selectors ".a,.b" --out impl.ir.json \
 *        [--width 1920] [--basic-auth user:pass]
 *
 * Requires playwright reachable (npm i playwright, or PLAYWRIGHT_BROWSERS_PATH set).
 */
const fs = require('fs');

function arg(name, def) {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}

function resolvePlaywright() {
  for (const p of ['playwright', '/Users/guntrambechtold/node_modules/playwright',
                   '/private/tmp/node_modules/playwright', process.env.HOME + '/node_modules/playwright']) {
    try { return require(p); } catch (e) {}
  }
  throw new Error('playwright not found — npm i playwright');
}

(async () => {
  const url = arg('url');
  const out = arg('out');
  const width = parseInt(arg('width', '1920'), 10);
  const selectors = (arg('selectors', '') || '').split(',').map(s => s.trim()).filter(Boolean);
  const ba = arg('basic-auth');
  if (!url || !selectors.length) { console.error('need --url and --selectors'); process.exit(2); }

  const { chromium } = resolvePlaywright();
  const browser = await chromium.launch();
  const ctxOpts = { viewport: { width, height: 1080 }, deviceScaleFactor: 1, reducedMotion: 'reduce' };
  if (ba) { const [u, p] = ba.split(':'); ctxOpts.httpCredentials = { username: u, password: p }; }
  const ctx = await browser.newContext(ctxOpts);
  const page = await ctx.newPage();
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => (document.fonts && document.fonts.ready) ? document.fonts.ready : null);
  await page.waitForTimeout(400);

  const elements = [];
  for (const sel of selectors) {
    const data = await page.evaluate((sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      const toHex = (c) => {
        const m = c.match(/\d+(\.\d+)?/g); if (!m) return null;
        const [r, g, b] = m.map(Number);
        return '#' + [r, g, b].map(n => n.toString(16).padStart(2, '0')).join('').toUpperCase();
      };
      return {
        bounds: { x: Math.round(r.x), y: Math.round(r.y + window.scrollY), w: Math.round(r.width), h: Math.round(r.height) },
        typography: {
          fontFamily: cs.fontFamily, fontSize: parseFloat(cs.fontSize),
          lineHeight: cs.lineHeight === 'normal' ? 0 : parseFloat(cs.lineHeight),
          letterSpacing: cs.letterSpacing === 'normal' ? 0 : parseFloat(cs.letterSpacing),
          weight: cs.fontWeight, transform: cs.textTransform, align: cs.textAlign,
        },
        color: { fill: toHex(cs.color), bg: toHex(cs.backgroundColor), opacity: parseFloat(cs.opacity) },
        radius: parseFloat(cs.borderTopLeftRadius) || 0,
        text: (el.textContent || '').trim().slice(0, 80),
      };
    }, sel);
    if (data) {
      elements.push({ id: sel, type: 'text', name: data.text, bounds: data.bounds,
        typography: data.typography, color: { fill: data.color.fill, opacity: data.color.opacity },
        bg: data.color.bg, radius: data.radius, text: data.text,
        fidelity: { bounds: 'exact', typography: 'exact', color: 'exact' } });
    } else {
      elements.push({ id: sel, type: 'text', bounds: { x: 0, y: 0, w: 0, h: 0 },
        fidelity: { bounds: 'manual' }, missing: true });
    }
  }
  await browser.close();

  const ir = { meta: { source: 'dom', side: 'implementation', unit: 'px', canvasWidth: width, generatedAt: new Date(0).toISOString() }, elements };
  if (out) { fs.writeFileSync(out, JSON.stringify(ir, null, 2)); console.error('IR written: ' + out + ' (' + elements.length + ' elements)'); }
  else { process.stdout.write(JSON.stringify(ir, null, 2)); }
})().catch(e => { console.error(e.message); process.exit(1); });
