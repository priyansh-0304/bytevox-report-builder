import { h, clear } from '../dom.js';
import { api } from '../api.js';
import { errorBox, openDialog, tableWrap } from '../ui.js';
import { when } from '../format.js';

const EXPIRIES = [[1, '1 hour'], [24, '24 hours'], [168, '7 days'], [720, '30 days']];

async function copyText(input, button) {
  try {
    await navigator.clipboard.writeText(input.value);
    button.textContent = 'Copied';
  } catch {
    input.select();                       // clipboard API blocked: let the user press Ctrl/Cmd+C
    button.textContent = 'Now press Ctrl+C';
  }
}

/** The "Share this report" dialog: create an expiring link, see existing links, revoke them. */
export function openShareDialog(reportId) {
  const created = h('div', { 'aria-live': 'polite' });
  const list = h('div');
  const expiry = h('select', { id: 'expiry', value: '168' }, EXPIRIES.map(([v, l]) => h('option', { value: String(v) }, l)));
  const createBtn = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
    createBtn.disabled = true;
    clear(created);
    try {
      const r = await api('POST', `/api/reports/${reportId}/shares`, { expires_in_hours: Number(expiry.value) });
      const url = new URL(r.path, location.origin).href;
      const input = h('input', { type: 'text', readOnly: true, value: url, 'aria-label': 'Share link' });
      const copy = h('button', { class: 'btn', type: 'button', onclick: () => copyText(input, copy) }, 'Copy');
      created.append(h('div', { class: 'stack' },
        h('div', { class: 'copy-row' }, input, copy),
        h('p', { class: 'notice' }, `Copy this link now. It expires ${when(r.expires_at)}. For safety the full link is shown only once; afterwards only its last 4 characters are kept.`)));
      input.focus(); input.select();
      await loadList();
    } catch (err) { created.append(errorBox(err)); }
    createBtn.disabled = false;
  } }, 'Create link');

  async function loadList() {
    try {
      const shares = await api('GET', `/api/reports/${reportId}/shares`);
      clear(list).append(shares.length ? tableWrap('Share links', h('table', null,
        h('thead', null, h('tr', null, ['Link', 'Status', 'Created', 'Expires', ''].map((t) => h('th', null, t)))),
        h('tbody', null, shares.map((s) => h('tr', null,
          h('td', null, `…${s.token_hint}`),
          h('td', null, h('span', { class: `badge ${s.status}` }, s.status)),
          h('td', null, when(s.created_at)),
          h('td', null, when(s.expires_at)),
          h('td', null, s.status === 'active' ? h('button', { class: 'btn small danger', type: 'button',
            'aria-label': `Revoke link ending ${s.token_hint}`, onclick: async () => {
              try { await api('DELETE', `/api/reports/${reportId}/shares/${s.id}`); await loadList(); }
              catch (err) { clear(list).append(errorBox(err)); }
            } }, 'Revoke') : null)))))) : h('p', { class: 'muted' }, 'No links yet.'));
    } catch (err) { clear(list).append(errorBox(err)); }
  }

  openDialog('Share this report', h('div', { class: 'stack' },
    h('p', { class: 'notice' }, 'Anyone with a link can see this report’s numbers, charts and any table rows it shows, until the link expires or you revoke it. They cannot see your file, your other reports or your account, and they cannot change anything.'),
    h('div', { class: 'row' }, h('label', { class: 'field', for: 'expiry' }, 'Link expires after', expiry), createBtn),
    created,
    h('h3', null, 'Links for this report'),
    list));
  loadList();
}
