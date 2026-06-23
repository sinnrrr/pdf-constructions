import * as pdfjsLib from 'pdfjs-dist/legacy/build/pdf.mjs';
import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.mjs?url';
pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;

const CODE_RE    = /^[А-ЯҐЄІЇа-яґєії]{1,5}-\d{1,3}[А-ЯҐЄІЇа-яґєії]?$/;
const CALC_RE    = /^\d+[,.]\d+x\d+[,.]\d+=\d+[,.]\d+$/;
const DECIMAL_RE = /^\d+[,.]\d{2}$/;
const FILTERED   = new Set(['Дв']);

// PDF.js getTextContent y grows upward; flip so the Дв distance filter matches
// the PyMuPDF reference. col detection is skipped (page content > 1.5MB) → 0.
function analyze(items, pageH) {
  const words = items.map(it => {
    const [, , c, d, e, f] = it.transform;
    const h = it.height || Math.hypot(c, d);
    return { x0: e, y0: pageH - (f + h), text: it.str };
  }).filter(w => w.text.trim().length);

  const decimals = words.filter(w => DECIMAL_RE.test(w.text.trim()))
    .map(w => [w.x0, w.y0, parseFloat(w.text.trim().replace(',', '.'))]);
  const calcs = words.filter(w => CALC_RE.test(w.text.trim())).map(w => [w.x0, w.y0]);
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

const $ = id => document.getElementById(id);
const canvas = $('canvas'), ctx = canvas.getContext('2d');
let pdf = null, pageNum = 1, renderTask = null;

window.addEventListener('resize', () => { clearTimeout(window._rt); window._rt = setTimeout(() => pdf && show(), 150); });

$('open').onclick = () => $('file').click();
$('file').onchange = async e => {
  const f = e.target.files[0];
  if (!f) return;
  const data = await f.arrayBuffer();
  pdf = await pdfjsLib.getDocument({
    data, isEvalSupported: false, useSystemFonts: true,
  }).promise;
  pageNum = 1;
  show();
};
$('prev').onclick = () => { if (pdf && pageNum > 1) { pageNum--; show(); } };
$('next').onclick = () => { if (pdf && pageNum < pdf.numPages) { pageNum++; show(); } };

function renderTable(counts) {
  const tbody = $('tbl').querySelector('tbody');
  const entries = Object.entries(counts).sort((a, b) => a[0].localeCompare(b[0], 'uk'));
  const total = entries.reduce((s, [, n]) => s + n, 0);
  tbody.innerHTML = entries
    .map(([k, n]) => `<tr><td>${k}</td><td class="num">${n}</td></tr>`).join('')
    + `<tr class="total"><td>Всього</td><td class="num">${total}</td></tr>`;
}

async function show() {
  $('pageinfo').textContent = `${pageNum}/${pdf.numPages}`;
  $('status').textContent = 'Аналізую...';
  $('tbl').querySelector('tbody').innerHTML = '';

  const page = await pdf.getPage(pageNum);
  const dpr = window.devicePixelRatio || 1;
  const wrapW = $('canvas-wrap').clientWidth - 20;
  const base = page.getViewport({ scale: 1 });
  const scale = wrapW / base.width;
  const vp = page.getViewport({ scale });
  canvas.width = vp.width * dpr;
  canvas.height = vp.height * dpr;
  canvas.style.width = vp.width + 'px';
  canvas.style.height = vp.height + 'px';
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  if (renderTask) renderTask.cancel();
  renderTask = page.render({ canvasContext: ctx, viewport: vp });
  const text = page.getTextContent();
  try { await renderTask.promise; } catch { /* cancelled */ }

  const content = await text;
  renderTable(analyze(content.items, base.height));
  $('status').textContent = '';
}
