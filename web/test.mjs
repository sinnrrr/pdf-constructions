import * as pdfjsLib from 'pdfjs-dist/legacy/build/pdf.mjs';

const URL = 'file:///Users/sinnrrr/Downloads/%D0%9A%D0%B0%D1%80%D0%B4%D0%B0%D0%BC%D0%BE%D0%BD_%D0%90%D0%A0_%D0%A0%D0%9F_%D0%B7_%D1%80%D0%B5%D0%B0%D0%BB%D1%8C%D0%BD%D0%B8%D0%BC%D0%B8_%D0%B2%D1%96%D0%B4%D0%BC%D1%96%D1%82%D0%BA%D0%B0%D0%BC%D0%B8_2.pdf';

const CODE_RE    = /^[А-ЯҐЄІЇа-яґєії]{1,5}-\d{1,3}[А-ЯҐЄІЇа-яґєії]?$/;
const CALC_RE    = /^\d+[,.]\d+x\d+[,.]\d+=\d+[,.]\d+$/;
const DECIMAL_RE = /^\d+[,.]\d{2}$/;
const FILTERED   = new Set(['Дв']);

// PDF.js item -> {x0,y0,x1,y1,text}. transform=[a,b,c,d,e,f]; e,f = origin.
// getTextContent y grows upward; Python (PyMuPDF) y grows downward. Flip y so
// the Дв distance filter uses the same orientation as the reference.
function itemBox(it, pageH) {
  const [a, b, c, d, e, f] = it.transform;
  const w = it.width, h = it.height || Math.hypot(c, d);
  const x0 = e, y0 = pageH - (f + h), x1 = e + w, y1 = pageH - f;
  return { x0, y0, x1, y1, text: it.str };
}

function analyze(items, pageH) {
  const words = items
    .map(it => itemBox(it, pageH))
    .filter(w => w.text.trim().length);

  const decimals = words
    .filter(w => DECIMAL_RE.test(w.text.trim()))
    .map(w => [w.x0, w.y0, parseFloat(w.text.trim().replace(',', '.'))]);
  const calcs = words
    .filter(w => CALC_RE.test(w.text.trim()))
    .map(w => [w.x0, w.y0]);
  const hasCalcs = calcs.length > 0;

  const isReal = (x0, y0) => hasCalcs
    ? calcs.some(([cx, cy]) => Math.hypot(cx - x0, cy - y0) <= 115)
    : decimals.some(([dx, dy, v]) => v <= 2.5 && Math.abs(dx - x0) < 80 && Math.abs(dy - y0) < 80);

  const counts = {};
  for (const w of words) {
    const t = w.text.trim();
    if (!CODE_RE.test(t)) continue;
    const prefix = t.slice(0, t.lastIndexOf('-'));
    if (FILTERED.has(prefix) && !isReal(w.x0, w.y0)) continue;
    counts[prefix] = (counts[prefix] || 0) + 1;
  }
  return counts;
}

const pdf = await pdfjsLib.getDocument({
  url: URL, useWorkerFetch: false, isEvalSupported: false, useSystemFonts: true,
}).promise;
const page = await pdf.getPage(23);
const vp = page.getViewport({ scale: 1 });
const content = await page.getTextContent();

console.log('items:', content.items.length);
console.log('first 20:', content.items.slice(0, 20).map(i => JSON.stringify(i.str)).join(' '));
const codeLike = content.items.filter(i => CODE_RE.test(i.str.trim()));
console.log('CODE_RE matches:', codeLike.length, codeLike.slice(0, 40).map(i => i.str).join(' '));

const counts = analyze(content.items, vp.height);
console.log('COUNTS:', counts);
const total = Object.values(counts).reduce((a, b) => a + b, 0);
console.log('Всього:', total);

const ok = counts['Вк'] === 19 && counts['Вт'] === 1 && counts['Дв'] === 32 && total === 52;
console.log(ok ? 'PASS' : 'FAIL');
process.exit(0);
