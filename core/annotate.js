#!/usr/bin/env node
/* annotate.js — draw numbered observation labels over a background, screenshot it.
 *
 * Background is either a live URL or a local image (the rasterized design comp).
 * Boxes come from a JSON file: [{x,y,w,h,label,verdict,caption}] in the background's
 * pixel space (live = DOM px @ width; design = raster px, 1pt→1px).
 *
 * Usage:
 *   node annotate.js --url <url> --boxes boxes.json --out impl.png --width 1920 [--basic-auth u:p]
 *   node annotate.js --image comp.png --boxes boxes.json --out design.png
 */
const fs = require('fs');
const path = require('path');

function arg(n, d) { const i = process.argv.indexOf('--' + n); return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : d; }
function resolvePlaywright() {
  for (const p of ['playwright', '/Users/guntrambechtold/Sites/indiewandern/evals/node_modules/playwright',
                   '/private/tmp/node_modules/playwright', '/Users/guntrambechtold/node_modules/playwright']) {
    try { return require(p); } catch (e) {}
  }
  throw new Error('playwright not found');
}

const COLOR = { pass: '#2F7A3E', warn: '#C9892B', fail: '#CF3329' };

function markerCss() {
  return `
   .hifi-mk{position:absolute;box-sizing:border-box;border:2px solid;z-index:2147483646;pointer-events:none;}
   .hifi-bd{position:absolute;top:-2px;left:-2px;font:700 13px/1.4 -apple-system,sans-serif;color:#fff;padding:1px 7px;border-radius:0 0 8px 0;}
   .hifi-cap{position:absolute;top:-2px;left:24px;font:600 11px/1.5 -apple-system,sans-serif;color:#fff;background:rgba(0,0,0,.72);padding:1px 6px;border-radius:0 6px 6px 0;white-space:nowrap;}`;
}

function injectScript(boxes) {
  return `(${function (boxes, COLOR) {
    const wrap = document.createElement('div');
    wrap.style.cssText = 'position:absolute;top:0;left:0;width:0;height:0;z-index:2147483646';
    boxes.forEach(function (b) {
      const c = COLOR[b.verdict] || '#888';
      const mk = document.createElement('div');
      mk.className = 'hifi-mk';
      mk.style.left = b.x + 'px'; mk.style.top = b.y + 'px';
      mk.style.width = b.w + 'px'; mk.style.height = b.h + 'px';
      mk.style.borderColor = c;
      mk.innerHTML = '<span class="hifi-bd" style="background:' + c + '">' + b.label + '</span>'
        + (b.caption ? '<span class="hifi-cap">' + b.caption + '</span>' : '');
      wrap.appendChild(mk);
    });
    document.body.appendChild(wrap);
  }})(${JSON.stringify(boxes)}, ${JSON.stringify(COLOR)})`;
}

(async () => {
  const url = arg('url'), image = arg('image'), out = arg('out');
  const width = parseInt(arg('width', '1920'), 10);
  const ba = arg('basic-auth');
  const boxes = JSON.parse(fs.readFileSync(arg('boxes'), 'utf-8'));

  const { chromium } = resolvePlaywright();
  const browser = await chromium.launch();
  const opts = { viewport: { width, height: 1080 }, deviceScaleFactor: 1, reducedMotion: 'reduce' };
  if (ba) { const [u, p] = ba.split(':'); opts.httpCredentials = { username: u, password: p }; }
  const ctx = await browser.newContext(opts);
  const page = await ctx.newPage();

  if (image) {
    const abs = path.resolve(image);
    // HTML neben das Bild schreiben + per file:// navigieren (same-origin → Bild lädt,
    // setContent+file:// würde von Playwright blockiert).
    const htmlPath = path.join(path.dirname(abs), '_annot.html');
    fs.writeFileSync(htmlPath, `<!doctype html><html><head><meta charset="utf-8"><style>*{margin:0}${markerCss()}</style></head>`
      + `<body><img id="bg" src="${path.basename(abs)}" style="display:block;width:100%"></body></html>`);
    await page.setViewportSize({ width, height: 1080 });
    await page.goto('file://' + htmlPath, { waitUntil: 'load' });
    await page.waitForFunction(() => { const i = document.getElementById('bg'); return i && i.complete && i.naturalWidth > 0; }, null, { timeout: 30000 });
  } else if (url) {
    await page.addStyleTag({ content: markerCss() }).catch(() => {});
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => (document.fonts && document.fonts.ready) ? document.fonts.ready : null);
    await page.waitForTimeout(500);
    await page.addStyleTag({ content: markerCss() });
  } else { console.error('need --url or --image'); process.exit(2); }

  await page.evaluate(injectScript(boxes));
  await page.screenshot({ path: out, fullPage: true });
  await browser.close();
  console.error('annotated: ' + out + ' (' + boxes.length + ' markers)');
})().catch(e => { console.error(e.message); process.exit(1); });
