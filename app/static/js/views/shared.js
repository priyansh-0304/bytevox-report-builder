import { h, clear } from '../dom.js';
import { api } from '../api.js';
import { errorBox, loading } from '../ui.js';
import { renderResult, summaryLine } from '../blocks.js';
import { when } from '../format.js';

/** The public page behind a share link. Read-only: there are no edit controls and no sign-in. */
export async function sharedView(root, token) {
  clear(root).append(loading('Loading shared report…'));
  try {
    const v = await api('GET', `/api/shared/${encodeURIComponent(token)}`, undefined, { quiet: true });
    document.title = `${v.title} · Shared report`;
    clear(root).append(
      h('div', { class: 'spread' }, h('h1', null, v.title),
        h('button', { class: 'btn', type: 'button', onclick: () => window.print() }, 'Print / PDF')),
      h('p', { class: 'muted' }, `Shared read-only. This link expires ${when(v.expires_at)}.`),
      summaryLine(v.summary),
      h('ul', { class: 'blocks' }, v.results.map((r) =>
        h('li', { class: r.type === 'metric' || r.type === 'note' ? '' : 'wide' }, renderResult(r)))));
  } catch (err) {
    document.title = 'Link unavailable';
    clear(root).append(h('div', { class: 'card stack' }, h('h1', null, 'This link is not available'),
      errorBox(err), h('p', { class: 'muted' }, 'Ask the person who sent it for a new link.')));
  }
}
