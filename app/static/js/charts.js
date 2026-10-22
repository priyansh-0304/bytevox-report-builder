// Hand-built SVG charts. They only DRAW the numbers the server sent; nothing is recalculated here.
import { s } from './dom.js';
import { num, compact } from './format.js';

const trunc = (text, n) => (String(text).length > n ? String(text).slice(0, n - 1) + '…' : String(text));
const tipText = (p) => `${p.x}: ${num(p.y)} (${num(p.rows)} ${p.rows === 1 ? 'row' : 'rows'})`;

// ---- one shared tooltip for every chart. Text is set with textContent, positions with the CSSOM
// (both allowed by our strict Content-Security-Policy).
let tip;
function showTip(text, x, y) {
  if (!tip) {
    tip = document.createElement('div');
    tip.className = 'tooltip';
    tip.setAttribute('aria-hidden', 'true');   // charts are described by their aria-label and data table
    document.body.append(tip);
  }
  tip.hidden = false;
  tip.textContent = text;
  tip.style.left = `${Math.min(x, window.innerWidth - 240)}px`;
  tip.style.top = `${y}px`;
}
const hideTip = () => { if (tip) tip.hidden = true; };

function enableTooltips(svg) {
  svg.addEventListener('pointermove', (e) => {
    const el = e.target.closest ? e.target.closest('[data-tip]') : null;
    if (el) showTip(el.getAttribute('data-tip'), e.clientX, e.clientY); else hideTip();
  });
  svg.addEventListener('pointerleave', hideTip);
}

/** Horizontal bars: long category names stay readable on a phone. */
export function barChart(points, label) {
  const W = 420, LABEL = 120, RIGHT = 64, ROW = 28, PAD = 6;
  const H = points.length * ROW + PAD * 2;
  const values = points.map((p) => p.y);
  const min = Math.min(0, ...values), max = Math.max(0, ...values);
  const span = max - min || 1;
  const inner = W - LABEL - RIGHT;
  const zeroX = LABEL + ((0 - min) / span) * inner;

  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': label, class: 'chart-svg' });
  points.forEach((p, i) => {
    const y = PAD + i * ROW;
    const w = (Math.abs(p.y) / span) * inner;
    const x = p.y >= 0 ? zeroX : zeroX - w;
    svg.append(
      s('rect', { x: LABEL, y: y + 4, width: inner, height: ROW - 8, rx: 4, class: 'chart-track' }),
      s('text', { x: LABEL - 8, y: y + ROW / 2, 'text-anchor': 'end', 'dominant-baseline': 'middle', class: 'chart-label' }, trunc(p.x, 16)),
      s('rect', { x, y: y + 4, width: Math.max(w, 1), height: ROW - 8, rx: 4, class: 'chart-bar' }),
      // value labels always sit to the right of the zero line, so negative bars never collide with names
      s('text', { x: (p.y >= 0 ? x + w : zeroX) + 6, y: y + ROW / 2, 'dominant-baseline': 'middle', class: 'chart-value' }, num(p.y)),
      // invisible full-row target on top: hover highlight + tooltip
      s('rect', { x: 0, y, width: W, height: ROW, class: 'chart-hit', 'data-tip': tipText(p) }),
    );
  });
  svg.append(s('line', { x1: zeroX, x2: zeroX, y1: PAD, y2: H - PAD, class: 'chart-zero' }));
  enableTooltips(svg);
  return svg;
}

// '2024' | '2024-03' | '2024-03-15'  ->  a timestamp, so points sit at their true position in time
const toTime = (x) => { const [y, m = '1', d = '1'] = x.split('-'); return Date.UTC(+y, +m - 1, +d); };
let gradientCount = 0;   // gradient ids must be unique per chart on the page

export function lineChart(points, label) {
  const W = 420, H = 240, L = 52, R = 14, T = 14, B = 30;
  const times = points.map((p) => toTime(p.x));
  const values = points.map((p) => p.y);
  const min = Math.min(0, ...values), max = Math.max(0, ...values);
  const span = max - min || 1;
  const t0 = Math.min(...times), tSpan = Math.max(...times) - t0 || 1;
  const X = (i) => (points.length === 1 ? L + (W - L - R) / 2 : L + ((times[i] - t0) / tSpan) * (W - L - R));
  const Y = (v) => T + (1 - (v - min) / span) * (H - T - B);
  const gid = `area-${++gradientCount}`;

  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': label, class: 'chart-svg' });
  svg.append(s('defs', {}, s('linearGradient', { id: gid, x1: '0', y1: '0', x2: '0', y2: '1' },
    s('stop', { offset: '0', class: 'chart-stop-top' }), s('stop', { offset: '1', class: 'chart-stop-bottom' }))));
  for (let i = 0; i <= 4; i++) {
    const v = min + (span * i) / 4;
    svg.append(
      s('line', { x1: L, x2: W - R, y1: Y(v), y2: Y(v), class: 'chart-grid' }),
      s('text', { x: L - 6, y: Y(v), 'text-anchor': 'end', 'dominant-baseline': 'middle', class: 'chart-axis' }, compact(v)));
  }
  const last = points.length - 1;
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(p.y).toFixed(1)}`).join(' ');
  if (points.length > 1) {   // soft area under the line, down to the zero line
    svg.append(s('path', { d: `${d} L${X(last).toFixed(1)},${Y(0).toFixed(1)} L${X(0).toFixed(1)},${Y(0).toFixed(1)} Z`, fill: `url(#${gid})` }));
  }
  svg.append(s('path', { d, class: 'chart-line' }));
  if (points.length <= 60) {
    points.forEach((p, i) => svg.append(s('circle', { cx: X(i), cy: Y(p.y), r: 3.5, class: 'chart-dot' })));
  }
  svg.append(s('text', { x: X(0), y: H - 8, 'text-anchor': 'start', class: 'chart-axis' }, points[0].x));
  if (last > 0) svg.append(s('text', { x: X(last), y: H - 8, 'text-anchor': 'end', class: 'chart-axis' }, points[last].x));
  // invisible hover targets on top of every point
  points.forEach((p, i) => svg.append(s('circle', { cx: X(i), cy: Y(p.y), r: 9, class: 'chart-hit', 'data-tip': tipText(p) })));
  enableTooltips(svg);
  return svg;
}