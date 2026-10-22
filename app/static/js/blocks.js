// Draws one computed block. Used by BOTH the report editor and the public share page,
// so the owner and a viewer see exactly the same thing.
import { h } from './dom.js';
import { barChart, lineChart } from './charts.js';
import { cell, num, plural } from './format.js';
import { openDialog, tableWrap } from './ui.js';

export function explainDialog(result) {
  const e = result.explain;
  const r = e.rows;
  const rowLine = (label, n, strong) => h('tr', null,
    h('td', null, strong ? h('strong', null, label) : label),
    h('td', { class: 'num' }, strong ? h('strong', null, num(n)) : num(n)));
  const body = h('div', { class: 'stack' },
    h('section', null, h('h3', null, 'In plain English'), h('p', null, e.description)),
    h('section', null,
      h('h3', null, 'The query'),
      h('pre', { class: 'query' }, e.query),
      h('p', { class: 'muted' }, e.computed_with)),
    h('section', null,
      h('h3', null, 'Rows'),
      tableWrap('Row counts', h('table', null, h('tbody', null,
        rowLine('Rows in your file', r.total),
        rowLine('Left out by the report filter', r.excluded_by_filter),
        r.excluded_no_group ? rowLine('Left out: no value to group by', r.excluded_no_group) : null,
        rowLine('Left out: blank or unreadable value', r.excluded_no_value),
        rowLine('Rows used in this result', r.used, true))))),
    e.notes.length ? h('section', null, h('h3', null, 'Good to know'), h('ul', null, e.notes.map((n) => h('li', null, n)))) : null);
  return openDialog(`How was “${result.title}” calculated?`, body);
}

const footer = (result) => {
  const r = result.explain.rows;
  return h('div', { class: 'block-foot' },
    h('span', null, `Used ${num(r.used)} of ${num(r.total)} rows`),
    h('button', { class: 'btn small', type: 'button', onclick: () => explainDialog(result) }, 'How was this calculated?'));
};

function metricBody(r) {
  const parts = [h('div', { class: 'big-number' }, r.value == null ? 'No data' : num(r.value))];
  if (r.value == null) parts.push(h('p', { class: 'muted' }, 'No rows match the current filter, or none have a readable value.'));
  if (r.groups) {
    parts.push(tableWrap(`${r.title} by group`, h('table', null,
      h('thead', null, h('tr', null, h('th', null, 'Group'), h('th', { class: 'num' }, 'Value'), h('th', { class: 'num' }, 'Rows'))),
      h('tbody', null, r.groups.map((g) => h('tr', null, h('td', null, g.key), h('td', { class: 'num' }, num(g.value)), h('td', { class: 'num' }, num(g.rows))))))));
  }
  return parts;
}

function chartBody(r) {
  if (!r.points.length) return [h('p', { class: 'muted' }, 'Nothing to chart: no rows match the filter, or none have the needed values.')];
  const label = `${r.title}: ${r.points.length} ${r.kind === 'line' ? 'points' : 'bars'}`;
  const svg = r.kind === 'line' ? lineChart(r.points, label) : barChart(r.points, label);
  const data = tableWrap(`${r.title} data`, h('table', null,
    h('thead', null, h('tr', null, h('th', null, 'Group'), h('th', { class: 'num' }, 'Value'), h('th', { class: 'num' }, 'Rows'))),
    h('tbody', null, r.points.map((p) => h('tr', null, h('td', null, p.x), h('td', { class: 'num' }, num(p.y)), h('td', { class: 'num' }, num(p.rows)))))));
  return [svg, h('details', null, h('summary', null, 'View chart data as a table'), data)];
}

function tableBody(r) {
  if (!r.rows.length) return [h('p', { class: 'muted' }, 'No rows to show: none match the filter, or none have a value to rank by.')];
  return [tableWrap(r.title, h('table', null,
    h('thead', null, h('tr', null, h('th', { class: 'num' }, 'Row'), r.columns.map((c) => h('th', null, c)))),
    h('tbody', null, r.rows.map((row) => h('tr', null,
      h('td', { class: 'num muted' }, row.row),
      row.cells.map((v) => h('td', { class: typeof v === 'number' ? 'num' : '' }, cell(v))))))))];
}

/** Returns the card content for one result. `tools` (optional) is extra header content for the editor. */
export function renderResult(result, tools) {
  const head = (title) => h('div', { class: 'spread' }, h('h3', null, title), tools || null);
  if (result.error) {
    return h('div', { class: 'block' }, head('Block'),
      h('p', { class: 'alert', role: 'alert' }, `This block could not be calculated: ${result.error}`));
  }
  if (result.type === 'note') {
    return h('div', { class: 'block' }, tools ? head('Note') : null,
      result.text ? h('p', { class: 'note-text' }, result.text) : h('p', { class: 'muted' }, 'Empty note.'));
  }
  const body = { metric: metricBody, chart: chartBody, table: tableBody }[result.type](result);
  const isKpi = result.type === 'metric' && !result.groups;   // a lone number gets the big "KPI card" look
  return h('div', { class: isKpi ? 'block kpi' : 'block' }, head(result.title), body, footer(result));
}

export function summaryLine(summary) {
  return h('p', { class: 'muted' },
    `Showing ${plural(summary.rows_after_filter, 'row', 'rows')} of ${num(summary.rows_total)}`,
    summary.filters_text ? ` where ${summary.filters_text}` : ' (no filter)', '.');
}

