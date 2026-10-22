import { h, clear, mount } from '../dom.js';
import { api } from '../api.js';
import { errorBox, loading, tableWrap } from '../ui.js';
import { cell, num } from '../format.js';

const stat = (label, value, hint) => h('div', { class: 'stat' }, h('b', null, num(value)), label,
  hint ? h('div', { class: 'muted' }, hint) : null);

const range = (c) => (c.min !== undefined ? `${cell(c.min)} → ${cell(c.max)}` : c.type === 'category' ? `${c.distinct} values` : '');
const KIND = { metric: 'Number', chart: 'Chart', table: 'Table' };

export async function datasetView(root, id) {
  clear(root).append(loading('Loading dataset…'));
  let d;
  try { d = await api('GET', `/api/datasets/${id}`); } catch (err) { clear(root).append(errorBox(err), h('a', { href: '#/' }, '← Back')); return; }
  document.title = `${d.name} · Show-your-work reports`;
  const p = d.profile;
  const problem = h('div', { 'aria-live': 'polite' });

  async function createReport(useSuggestions, button) {
    button.disabled = true;
    clear(problem);
    try {
      const r = await api('POST', '/api/reports', { dataset_id: d.id, title: `${d.name} report`, use_suggestions: useSuggestions });
      location.hash = `#/reports/${r.id}`;
    } catch (err) { button.disabled = false; problem.append(errorBox(err)); }
  }

  const blankBtn = h('button', { class: 'btn', type: 'button', onclick: () => createReport(false, blankBtn) }, 'Start a blank report');
  const suggestBtn = d.suggestions.length
    ? h('button', { class: 'btn primary', type: 'button', onclick: () => createReport(true, suggestBtn) },
      `Create report with these ${d.suggestions.length} suggestions`)
    : null;

  const deleteBtn = h('button', { class: 'btn danger', type: 'button', onclick: async () => {
    const extra = d.report_count
      ? ` This also deletes ${d.report_count} report${d.report_count === 1 ? '' : 's'} built on it and stops their share links.` : '';
    if (!confirm(`Delete “${d.name}” and all its rows?${extra} This cannot be undone.`)) return;
    deleteBtn.disabled = true;
    try { await api('DELETE', `/api/datasets/${d.id}`); location.hash = '#/'; }
    catch (err) { deleteBtn.disabled = false; problem.append(errorBox(err)); }
  } }, 'Delete this dataset');

  mount(root,
    h('p', null, h('a', { href: '#/' }, '← All datasets')),
    h('div', { class: 'spread' }, h('h1', null, d.name), h('div', { class: 'row center' }, blankBtn, suggestBtn)),
    problem,
    h('p', { class: 'muted' }, `From file “${d.original_filename}”. The original file is not kept, only the parsed rows.`),

    h('section', { class: 'card', 'aria-labelledby': 'sum-h' },
      h('h2', { id: 'sum-h' }, 'Profile'),
      h('div', { class: 'stats' },
        stat('rows imported', p.row_count),
        stat('rows rejected', p.rejected_count, p.rejected_count ? 'listed below with reasons' : 'none'),
        stat('records read', p.rows_read, 'imported + rejected'),
        stat('columns', p.columns.length)),
      p.warnings.length ? h('div', { class: 'notice stack' }, h('strong', null, 'Heads up'),
        h('ul', null, p.warnings.map((w) => h('li', null, w)))) : null),

    d.suggestions.length ? h('section', { class: 'card', 'aria-labelledby': 'sug-h' },
      h('h2', { id: 'sug-h' }, 'Suggested for this file'),
      h('p', { class: 'muted' }, 'Picked automatically from your column types (no AI, no guessing at random). Nothing is added until you click the button.'),
      h('ul', { class: 'cards suggestions' }, d.suggestions.map((s) => h('li', null, h('div', { class: 'suggest' },        h('strong', null, s.title), h('span', { class: 'muted' }, s.why),
        h('span', { class: 'badge' }, KIND[s.block.type]))))),
      h('div', { class: 'row section-action' }, h('button', { class: 'btn primary', type: 'button',        
        onclick: (e) => createReport(true, e.currentTarget) }, 'Create report with these suggestions'))) : null,

    h('section', { class: 'card', 'aria-labelledby': 'col-h' },
      h('h2', { id: 'col-h' }, 'Columns'),
      h('p', { class: 'muted' }, '“Blank” means empty, NA, null or similar. “Unreadable” means there was a value but it does not fit the column’s type (it is treated as missing and counted here, never hidden).'),
      tableWrap('Column profile', h('table', null,
        h('thead', null, h('tr', null, ['Column', 'Type', 'Blank', 'Unreadable', 'Distinct', 'Range / values'].map((t, i) => h('th', { class: i >= 2 && i <= 4 ? 'num' : '' }, t)))),
        h('tbody', null, p.columns.map((c) => h('tr', null,
          h('td', null, c.name), h('td', null, c.type), h('td', { class: 'num' }, num(c.missing)),
          h('td', { class: 'num' }, num(c.invalid)), h('td', { class: 'num' }, num(c.distinct)), h('td', null, range(c))))))),
      ...p.columns.filter((c) => c.invalid).map((c) => h('details', null,
        h('summary', null, `Unreadable values in “${c.name}” (${num(c.invalid)}), first ${c.invalid_samples.length}`),
        h('ul', null, c.invalid_samples.map((s) => h('li', null, `line ${s.line}: “${s.value}” (${s.reason})`)))))),

    h('section', { class: 'card', 'aria-labelledby': 'rej-h' },
      h('h2', { id: 'rej-h' }, 'Rejected rows'),
      p.rejected_count === 0 ? h('p', null, 'Every row in the file was readable.') : h('div', { class: 'stack' },
        h('p', { class: 'muted' }, `${num(p.rejected_count)} records could not be read and are NOT in your data.`
          + (p.rejected_count > p.rejected.length ? ` Showing the first ${p.rejected.length}.` : ''), ' Line numbers refer to your original file.'),
        tableWrap('Rejected rows', h('table', null,
          h('thead', null, h('tr', null, h('th', { class: 'num' }, 'Line'), h('th', null, 'Reason'), h('th', null, 'Content'))),
          h('tbody', null, p.rejected.map((r) => h('tr', null, h('td', { class: 'num' }, r.line), h('td', null, r.reason), h('td', null, r.preview || '—')))))))),

    h('section', { class: 'card', 'aria-labelledby': 'pre-h' },
      h('h2', { id: 'pre-h' }, 'First rows as imported'),
      tableWrap('Preview rows', h('table', null,
        h('thead', null, h('tr', null, h('th', { class: 'num' }, 'Line'), d.preview.columns.map((c) => h('th', null, c)))),
        h('tbody', null, d.preview.rows.map((r) => h('tr', null, h('td', { class: 'num muted' }, r.row),
          r.cells.map((v) => h('td', { class: typeof v === 'number' ? 'num' : '' }, cell(v))))))))),

    h('section', { class: 'card', 'aria-labelledby': 'del-h' },
      h('h2', { id: 'del-h' }, 'Delete this dataset'),
      h('p', { class: 'muted' }, d.report_count
        ? `This also deletes the ${d.report_count} report${d.report_count === 1 ? '' : 's'} built on it and stops their share links working.`
        : 'No reports use it yet. Deleting removes every imported row.'),
      deleteBtn));
}