import { h, clear } from './dom.js';

/** Skeleton placeholder lines. The screen-reader text says what is happening; the bars are decoration. */
export const loading = (text = 'Loading…', rows = 3) =>
  h('div', { class: 'skeletons', role: 'status' },
    h('span', { class: 'sr-only' }, text),
    Array.from({ length: rows }, () => h('div', { class: 'skeleton', 'aria-hidden': 'true' })));

export const errorBox = (err) =>
  h('p', { class: 'alert', role: 'alert' }, err instanceof Error ? err.message : String(err));

export const empty = (title, text) =>
  h('div', { class: 'empty' }, h('strong', null, title), text ? h('p', null, text) : null);

export function tableWrap(label, table) {
  // tabindex=0 lets keyboard users scroll a wide table
  return h('div', { class: 'table-wrap', tabindex: '0', role: 'region', 'aria-label': label }, table);
}

const dialog = () => document.getElementById('dialog');

export function closeDialog() {
  const d = dialog();
  if (d.open) d.close();
}

/** Shows `content` in the shared <dialog>. Esc closes it, focus is trapped inside, and focus returns
 *  to the button that opened it (all native <dialog> behaviour). */
export function openDialog(title, content) {
  const d = dialog();
  clear(d);
  d.append(h('div', { class: 'dialog-body' },
    h('div', { class: 'spread' },
      h('h2', { id: 'dialog-title' }, title),
      h('button', { class: 'btn small', type: 'button', onclick: closeDialog }, 'Close')),
    content));
  if (!d.open) d.showModal();
  d.onclick = (e) => { if (e.target === d) closeDialog(); };   // click on the backdrop
  return d;
}