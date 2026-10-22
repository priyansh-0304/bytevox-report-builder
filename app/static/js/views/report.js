import { h, clear, mount } from '../dom.js';
import { api } from '../api.js';
import { empty, errorBox, loading } from '../ui.js';
import { renderResult, summaryLine } from '../blocks.js';
import { openShareDialog } from './share.js';

const AGGS = [['sum', 'Sum'], ['avg', 'Average'], ['count', 'Count'], ['min', 'Minimum'], ['max', 'Maximum']];
const newId = () => Math.random().toString(36).slice(2, 10);

const select = (options, value, onchange, id) =>
  h('select', { id, value: value ?? '', onchange: (e) => onchange(e.target.value) },
    options.map(([v, l]) => h('option', { value: v }, l)));
const field = (label, control) => h('label', { class: 'field' }, label, control);

export async function reportView(root, id) {
  clear(root).append(loading('Loading report…'));
  let view;
  try { view = await api('GET', `/api/reports/${id}`); }
  catch (err) { clear(root).append(errorBox(err), h('a', { href: '#/' }, '← Back')); return; }
  document.title = `${view.title} · Show-your-work reports`;

  // ---- local state. The server is the source of truth: after every edit we PUT it, then redraw from the reply.
  let title = view.title;
  let blocks = structuredClone(view.blocks);
  let results = view.results;
  let summary = view.summary;
  let lastGood = view;
  const columns = view.dataset.columns;
  const colsOf = (...types) => columns.filter((c) => types.includes(c.type));
  const colType = (name) => columns.find((c) => c.name === name)?.type;
  const names = (cols) => cols.map((c) => [c.name, c.name]);
  const openEdits = new Set();       // which blocks have their settings panel open
  let focusKey = null;               // element to focus after the next redraw (keeps keyboard users in place)

  const ui = {                       // the report-level filter, as the form sees it
    dateCol: view.filters.date?.column ?? '', start: view.filters.date?.start ?? '', end: view.filters.date?.end ?? '',
    catCol: view.filters.category?.column ?? '', cats: new Set(view.filters.category?.values ?? []),
  };
  const filtersPayload = () => {
    const f = {};
    if (ui.dateCol && (ui.start || ui.end)) {
      f.date = { column: ui.dateCol };
      if (ui.start) f.date.start = ui.start;
      if (ui.end) f.date.end = ui.end;
    }
    if (ui.catCol && ui.cats.size) f.category = { column: ui.catCol, values: [...ui.cats] };
    return f;
  };

  // ---- saving: one request at a time, always sending the latest state
  const statusEl = h('p', { class: 'status', role: 'status' });
  const setStatus = (text, isError = false) => {
    statusEl.textContent = text;
    statusEl.className = `status${isError ? ' error' : ''}`;
    statusEl.setAttribute('role', isError ? 'alert' : 'status');
  };
  let queue = Promise.resolve();
  const save = () => (queue = queue.then(doSave));

  async function doSave() {
    setStatus('Saving…');
    try {
      const next = await api('PUT', `/api/reports/${id}`, { title, blocks, filters: filtersPayload() });
      lastGood = next;
      blocks = structuredClone(next.blocks); results = next.results; summary = next.summary;
      setStatus('All changes saved.');
    } catch (err) {
      setStatus(`Not saved: ${err.message} Your last saved version is shown.`, true);
      title = lastGood.title; blocks = structuredClone(lastGood.blocks);   // revert to what the server accepted
      results = lastGood.results; summary = lastGood.summary;
      titleInput.value = title;
      renderFilters();
    }
    renderBlocks();
  }

  // ---- block editing
  const colName = (b) => b.column ?? 'all rows';
  function normalize(b) {            // keep a block valid when one of its settings changes
    if (b.type === 'metric' || b.type === 'chart') {
      if (b.agg !== 'count' && colType(b.column) !== 'number') b.column = colsOf('number')[0]?.name ?? null;
    }
    if (b.type === 'metric' && b.group_by && colType(b.group_by) !== 'category') b.group_by = null;
    if (b.type === 'chart') {
      const want = b.kind === 'line' ? 'date' : 'category';
      if (colType(b.group_by) !== want) b.group_by = colsOf(want)[0]?.name ?? b.group_by;
    }
  }
  const change = (b, patch) => { Object.assign(b, patch); normalize(b); save(); };

  function addBlock(type) {
    const num = colsOf('number')[0]?.name ?? null;
    const cat = colsOf('category')[0]?.name, date = colsOf('date')[0]?.name;
    const agg = num ? 'sum' : 'count';
    let b;
    if (type === 'metric') b = { type, agg, column: num, group_by: null, title: null };
    else if (type === 'chart') {
      if (cat) b = { type, kind: 'bar', agg, column: num, group_by: cat, bucket: 'month', title: null };
      else if (date) b = { type, kind: 'line', agg, column: num, group_by: date, bucket: 'month', title: null };
      else { setStatus('Charts need a category or a date column, and this dataset has neither.', true); return; }
    } else if (type === 'table') b = { type, sort_by: num ?? columns[0].name, order: 'desc', limit: 10, columns: null, title: null };
    else b = { type: 'note', text: '' };
    b.id = newId();
    blocks.push(b);
    openEdits.add(b.id);
    focusKey = `${b.id}:grip`;
    save();
  }
  function move(i, delta) {
    const j = i + delta;
    [blocks[i], blocks[j]] = [blocks[j], blocks[i]];
    focusKey = `${blocks[j].id}:grip`;
    save();
  }

    function moveTo(from, to) {         // drag and drop: take the block out and put it where it was dropped
    const [moved] = blocks.splice(from, 1);
    blocks.splice(to, 0, moved);
    renderBlocks();                   // show the new order at once; save() then redraws from the server's answer
    save();
  }

  function remove(i) {
    const [gone] = blocks.splice(i, 1);
    openEdits.delete(gone.id);
    save().then(() => setStatus('Block removed.'));
  }

  function editForm(b) {
    const any = names(columns);
    const aggSelect = select(AGGS, b.agg, (v) => change(b, { agg: v }));
    const colOptions = b.agg === 'count' ? [['', 'All rows'], ...any] : names(colsOf('number'));
    const titleInput = h('input', { type: 'text', maxlength: '100', value: b.title ?? '', placeholder: 'Automatic',
      onchange: (e) => change(b, { title: e.target.value.trim() || null }) });
    const titleField = field('Title (optional)', titleInput);

    if (b.type === 'metric') return [
      field('Calculation', aggSelect),
      field('Column', select(colOptions, b.column ?? '', (v) => change(b, { column: v || null }))),
      field('Split by (optional)', select([['', 'Nothing'], ...names(colsOf('category'))], b.group_by ?? '', (v) => change(b, { group_by: v || null }))),
      titleField];
    if (b.type === 'chart') return [
      field('Chart type', select([['bar', 'Bar'], ['line', 'Line (over time)']], b.kind, (v) => change(b, { kind: v }))),
      field('Calculation', aggSelect),
      field('Column', select(colOptions, b.column ?? '', (v) => change(b, { column: v || null }))),
      field(b.kind === 'line' ? 'Date column (x axis)' : 'Category (x axis)',
        select(names(colsOf(b.kind === 'line' ? 'date' : 'category')), b.group_by ?? '', (v) => change(b, { group_by: v }))),
      b.kind === 'line' ? field('Group dates by', select([['day', 'Day'], ['month', 'Month'], ['year', 'Year']], b.bucket, (v) => change(b, { bucket: v }))) : null,
      titleField];
    if (b.type === 'table') {
      const chosen = new Set(b.columns ?? []);
      return [
        field('Rank by', select(any, b.sort_by, (v) => change(b, { sort_by: v }))),
        field('Order', select([['desc', 'Highest first'], ['asc', 'Lowest first']], b.order, (v) => change(b, { order: v }))),
        field('Rows to show (1–50)', h('input', { type: 'number', min: '1', max: '50', value: String(b.limit),
          onchange: (e) => change(b, { limit: Math.min(50, Math.max(1, Math.round(Number(e.target.value)) || 10)) }) })),
        h('fieldset', null, h('legend', null, 'Columns to show (none ticked = all)'),
          h('div', { class: 'checks' }, columns.map((c) => h('label', null,
            h('input', { type: 'checkbox', checked: chosen.has(c.name), onchange: (e) => {
              e.target.checked ? chosen.add(c.name) : chosen.delete(c.name);
              change(b, { columns: chosen.size ? columns.map((x) => x.name).filter((n) => chosen.has(n)) : null });
            } }), c.name)))),
        titleField];
    }
    return [h('label', { class: 'field' }, 'Note text',
      h('textarea', { maxlength: '2000', value: b.text, onchange: (e) => change(b, { text: e.target.value }) }))];
  }

  function blockCard(b, r, i) {
    const label = r.title || (b.type === 'note' ? 'note' : `${b.type} ${i + 1}`);
        const grip = h('span', { class: 'drag-handle', role: 'button', tabindex: '0', title: 'Drag to reorder',
      'aria-label': `Reorder “${label}”. Drag it with the mouse, or press the up or down arrow key.`,
      'data-key': `${b.id}:grip`,
      onkeydown: (e) => {            // keyboard users move a block with the arrow keys on its handle
        const delta = e.key === 'ArrowUp' ? -1 : e.key === 'ArrowDown' ? 1 : 0;
        if (!delta || i + delta < 0 || i + delta >= blocks.length) return;
        e.preventDefault();
        move(i, delta);
      } }, '⠿');
    const tools = h('div', { class: 'block-tools' }, grip,
      h('button', { class: 'btn small danger', type: 'button', 'aria-label': `Remove “${label}”`, onclick: () => remove(i) }, 'Remove'));const card = renderResult(r, tools);
    card.append(h('details', { open: openEdits.has(b.id), ontoggle: (e) => {
      e.target.open ? openEdits.add(b.id) : openEdits.delete(b.id);
    } }, h('summary', { 'data-key': `${b.id}:edit` }, 'Edit settings'), h('div', { class: 'edit-form' }, editForm(b))));
    return card;
  }

  // ---- page skeleton
  const titleInput = h('input', { class: 'title-input', type: 'text', maxlength: '100', value: title, 'aria-label': 'Report title',
    onchange: (e) => { title = e.target.value.trim() || 'Untitled report'; e.target.value = title; save(); } });
  const summaryEl = h('div');
  const blocksEl = h('ol', { class: 'blocks' });
  const filtersEl = h('section', { class: 'card', id: 'filters-card', 'aria-labelledby': 'flt-h' });
   
  // ---- drag to reorder: our own pointer-event drag (mouse, pen and finger share one code path).
  // Only the ⠿ handle starts a drag. While dragging you see a floating copy of the card and a blue line showing
  // where it will land. The landing spot is the slot NEAREST the pointer, so empty space beside a card works too.
  let drag = null;                       // { from, li, grip, id, x0, y0, offX, offY, started, ghost, pos, x, y }
  let bar = null;                        // the blue insertion line (created once, fixed to the viewport)
  let scrollSpeed = 0, scrollFrame = 0;

  function dropSlot(x, y) {              // -> { pos, wide, r, after } for the card nearest (x, y), or null
    let best = null;
    [...blocksEl.children].filter((el) => el.tagName === 'LI').forEach((li, i) => {
      const r = li.getBoundingClientRect();
      const d = Math.hypot(Math.max(r.left - x, 0, x - r.right), Math.max(r.top - y, 0, y - r.bottom));
      if (!best || d < best.d) best = { d, i, r, wide: li.classList.contains('wide') };
    });
    if (!best) return null;
    const after = best.wide ? y > (best.r.top + best.r.bottom) / 2 : x > (best.r.left + best.r.right) / 2;
    return { ...best, after, pos: best.i + (after ? 1 : 0) };
  }

  function refreshTarget() {             // redraw the ghost and the blue line for the current pointer position
    if (!drag || !drag.started) return;
    drag.ghost.style.transform = `translate(${drag.x - drag.offX}px, ${drag.y - drag.offY}px)`;
    const t = dropSlot(drag.x, drag.y);
    drag.pos = t ? t.pos : null;
    const to = t && (t.pos > drag.from ? t.pos - 1 : t.pos);
    if (!t || to === drag.from) { bar.hidden = true; drag.pos = null; return; }   // dropping here would change nothing
    bar.hidden = false;
    const st = bar.style;
    if (t.wide) { st.left = `${t.r.left}px`; st.width = `${t.r.width}px`; st.height = '4px'; st.top = `${t.after ? t.r.bottom + 6 : t.r.top - 10}px`; }
    else { st.top = `${t.r.top}px`; st.height = `${t.r.height}px`; st.width = '4px'; st.left = `${t.after ? t.r.right + 6 : t.r.left - 10}px`; }
  }

  // The page does not scroll by itself while you drag, so scroll when the pointer is near the top or bottom edge.
  function autoScrollStep() {
    if (!drag || !scrollSpeed) { scrollFrame = 0; return; }
    window.scrollBy(0, scrollSpeed);
    refreshTarget();                     // the cards moved under a still pointer
    scrollFrame = requestAnimationFrame(autoScrollStep);
  }
  function updateAutoScroll(y) {
    const EDGE = 110, TOP_EXTRA = 60;    // the sticky top bar covers the first ~60px
    const fromTop = y - TOP_EXTRA, fromBottom = window.innerHeight - y;
    scrollSpeed = fromTop < EDGE ? -Math.min(16, Math.ceil((EDGE - fromTop) / 4))
      : fromBottom < EDGE ? Math.min(16, Math.ceil((EDGE - fromBottom) / 4)) : 0;
    if (scrollSpeed && !scrollFrame) scrollFrame = requestAnimationFrame(autoScrollStep);
  }

  function startDrag(e) {
    const r = drag.li.getBoundingClientRect();
    drag.started = true;
    drag.offX = drag.x0 - r.left; drag.offY = drag.y0 - r.top;
    const ghost = drag.li.cloneNode(true);
    ghost.querySelectorAll('[id]').forEach((n) => n.removeAttribute('id'));    // no duplicate ids from the copy
    ghost.classList.add('drag-ghost');
    ghost.setAttribute('aria-hidden', 'true');
    ghost.style.width = `${r.width}px`;
    document.body.append(ghost);
    drag.ghost = ghost;
    if (!bar) { bar = h('div', { class: 'drop-indicator', hidden: true, 'aria-hidden': 'true' }); document.body.append(bar); }
    drag.li.classList.add('dragging');
    document.body.classList.add('is-dragging');
  }

  function endDrag(commit) {
    const d = drag;
    if (!d) return;
    drag = null;
    scrollSpeed = 0;
    d.ghost?.remove();
    if (bar) bar.hidden = true;
    d.li.classList.remove('dragging');
    document.body.classList.remove('is-dragging');
    try { d.grip.releasePointerCapture(d.id); } catch { /* already released */ }
    if (commit && d.started && d.pos !== null) moveTo(d.from, d.pos > d.from ? d.pos - 1 : d.pos);
  }

  function makeDraggable(li, i) {
    const grip = li.querySelector('.drag-handle');
    if (!grip) return;
    grip.addEventListener('pointerdown', (e) => {
      if (drag || (e.pointerType === 'mouse' && e.button !== 0)) return;
      drag = { from: i, li, grip, id: e.pointerId, x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY, started: false, pos: null };
      try { grip.setPointerCapture(e.pointerId); } catch { /* the pointer is gone */ }
      e.preventDefault();                // no text selection, no native image drag
    });
    grip.addEventListener('pointermove', (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      drag.x = e.clientX; drag.y = e.clientY;
      if (!drag.started) {
        if (Math.hypot(drag.x - drag.x0, drag.y - drag.y0) < 5) return;     // a click on the handle is not a drag
        startDrag(e);
      }
      refreshTarget();
      updateAutoScroll(e.clientY);
    });
    grip.addEventListener('pointerup', (e) => { if (drag && e.pointerId === drag.id) endDrag(true); });
    grip.addEventListener('pointercancel', () => endDrag(false));
    grip.addEventListener('lostpointercapture', () => endDrag(false));      // e.g. the card was redrawn mid-drag
    grip.addEventListener('keydown', (e) => { if (e.key === 'Escape' && drag) endDrag(false); });
  }

  function renderBlocks() {
    clear(summaryEl).append(summaryLine(summary));
    // A redraw replaces every card. Without these three steps the page is briefly short, the browser clamps the
    // scroll position, and you land near the top; and the control you were using loses keyboard focus.
    const scrollY = window.scrollY;
    blocksEl.style.minHeight = `${blocksEl.offsetHeight}px`;           // hold the page height while the cards are rebuilt
    const active = document.activeElement;
    const inForm = active && blocksEl.contains(active) && active.closest('.edit-form');
    const keep = !focusKey && inForm ? {                               // remember which settings control had focus
      card: [...blocksEl.children].indexOf(active.closest('.blocks > li')),
      control: [...inForm.querySelectorAll('select, input, textarea')].indexOf(active) } : null;

    clear(blocksEl);
    if (!blocks.length) {
      blocksEl.append(h('li', { class: 'wide' }, empty('This report is empty', 'Add a metric, chart, table or note with the buttons above.')));
    }
    blocks.forEach((b, i) => {
      const r = results.find((x) => x.id === b.id) ?? { id: b.id, type: b.type, error: 'Not calculated yet.' };
      const li = h('li', { class: r.type === 'metric' || r.type === 'note' ? '' : 'wide' }, blockCard(b, r, i));
      makeDraggable(li, i);
      blocksEl.append(li);
    });
    blocksEl.style.minHeight = '';
    window.scrollTo(0, scrollY);
    if (focusKey) { blocksEl.querySelector(`[data-key="${focusKey}"]`)?.focus(); focusKey = null; }
    else if (keep) {                                                   // put focus back without scrolling
      blocksEl.children[keep.card]?.querySelectorAll('.edit-form select, .edit-form input, .edit-form textarea')[keep.control]
        ?.focus({ preventScroll: true });
    }
  }

  function renderFilters(focusId) {
    const dateCols = colsOf('date'), catCols = colsOf('category');
    const onFilter = () => { save(); };
    const dateCol = colsOf('date').find((c) => c.name === ui.dateCol);
    const catCol = catCols.find((c) => c.name === ui.catCol);
      mount(filtersEl,
      h('h2', { id: 'flt-h' }, 'Filters'),
      h('p', { class: 'muted' }, 'A filter applies to every block in the report.'),
      h('div', { class: 'row' },
        dateCols.length ? [
          field('Date column', select([['', 'No date filter'], ...names(dateCols)], ui.dateCol, (v) => {
            ui.dateCol = v; ui.start = ui.end = ''; renderFilters('f-date-col'); onFilter();
          }, 'f-date-col')),
          ui.dateCol ? [
            field('From', h('input', { type: 'date', value: ui.start, min: dateCol?.min, max: dateCol?.max, onchange: (e) => { ui.start = e.target.value; onFilter(); } })),
            field('To', h('input', { type: 'date', value: ui.end, min: dateCol?.min, max: dateCol?.max, onchange: (e) => { ui.end = e.target.value; onFilter(); } })),
          ] : null,
        ] : h('p', { class: 'muted' }, 'No date column was found, so a date-range filter is not available.')),
      h('div', { class: 'row' },
        catCols.length ? [
          field('Category column', select([['', 'No category filter'], ...names(catCols)], ui.catCol, (v) => {
            ui.catCol = v; ui.cats = new Set(); renderFilters('f-cat-col'); onFilter();
          }, 'f-cat-col')),
        ] : h('p', { class: 'muted' }, 'No category column was found, so a category filter is not available.')),
      catCol ? h('fieldset', null, h('legend', null, `Show only these “${catCol.name}” values (none ticked = all)`),
        h('div', { class: 'checks' }, (catCol.categories ?? []).map((v) => h('label', null,
          h('input', { type: 'checkbox', checked: ui.cats.has(v), onchange: (e) => {
            e.target.checked ? ui.cats.add(v) : ui.cats.delete(v); onFilter();
          } }), v)))) : null);
    if (focusId) filtersEl.querySelector(`#${focusId}`)?.focus();
  }

  const addBtn = (type, text) => h('button', { class: 'btn', type: 'button', onclick: () => addBlock(type) }, text);

  clear(root).append(
    h('p', null, h('a', { href: `#/datasets/${view.dataset.id}` }, `← ${view.dataset.name}`)),
    h('div', { class: 'page-head' }, titleInput,
      h('button', { class: 'btn', type: 'button', onclick: () => window.print() }, 'Print / PDF'),
      h('button', { class: 'btn primary', type: 'button', onclick: () => openShareDialog(id) }, 'Share')),
    filtersEl,
    summaryEl,
    h('div', { class: 'row center add-bar', role: 'group', 'aria-label': 'Add a block' },      h('strong', null, 'Add:'), addBtn('metric', 'Metric'), addBtn('chart', 'Chart'), addBtn('table', 'Table'), addBtn('note', 'Note')),
    statusEl,
    blocksEl);
    renderFilters();
  renderBlocks();
  // The fade-in is for the first paint only. Re-running it after every edit or drop made the whole page flash.
  setTimeout(() => blocksEl.classList.add('settled'), 900);
}
