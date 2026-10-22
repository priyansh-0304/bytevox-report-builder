import { h, clear } from '../dom.js';
import { api, apiUpload } from '../api.js';
import { errorBox, empty, loading } from '../ui.js';
import { num, when } from '../format.js';

const kb = (bytes) => (bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);

export async function homeView(root) {
  document.title = 'Your workspace · Show-your-work reports';
  clear(root).append(h('h1', null, 'Your workspace'));

  // ---- upload: a drop zone that is still a real <input type="file">, so the keyboard works too
  const message = h('div', { 'aria-live': 'polite' });
  const file = h('input', { id: 'file', type: 'file', accept: '.csv,text/csv', required: true, class: 'dz-input' });
  const chosen = h('span', { class: 'dz-file muted' }, 'No file chosen yet');
  const showChosen = () => {
    const f = file.files[0];
    chosen.textContent = f ? `${f.name} · ${kb(f.size)}` : 'No file chosen yet';
  };
  file.addEventListener('change', showChosen);
  const zone = h('label', { class: 'dropzone', for: 'file' },
    file,
    h('span', { class: 'dz-icon', 'aria-hidden': 'true' }, '⬆'),
    h('strong', null, 'Drop a CSV here, or click to browse'),
    h('span', { class: 'muted' }, 'Up to 5 MB · UTF-8 · the first row must be column names'),
    chosen);
  ['dragenter', 'dragover'].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.remove('over'); }));
  zone.addEventListener('drop', (e) => {
    if (e.dataTransfer.files.length) { file.files = e.dataTransfer.files; showChosen(); }
  });

  const name = h('input', { id: 'dname', type: 'text', maxlength: '100', placeholder: 'Defaults to the file name' });
  const submit = h('button', { class: 'btn primary', type: 'submit' }, 'Upload and analyse');
  const form = h('form', { class: 'stack', onsubmit: async (ev) => {
    ev.preventDefault();
    clear(message);
    if (!file.files.length) { message.append(errorBox('Choose a CSV file first.')); return; }
    const body = new FormData();
    body.append('file', file.files[0]);
    body.append('name', name.value);
    submit.disabled = true;
    const phase = h('p', { class: 'muted' }, 'Uploading…');
    const bar = h('progress', { max: '1', 'aria-label': 'Upload progress' });
    bar.value = 0;
    message.append(h('div', { class: 'stack', role: 'status' }, phase, bar));
    try {
      const ds = await apiUpload('/api/datasets', body, (fraction) => {
        bar.value = fraction;
        if (fraction >= 1) phase.textContent = 'Analysing your file…';
      });
      location.hash = `#/datasets/${ds.id}`;
    } catch (err) {
      clear(message).append(errorBox(err));      // the form keeps its values so the user can try another file
      submit.disabled = false;
    }
  } },
    zone,
    h('div', { class: 'row' }, h('label', { class: 'field', for: 'dname' }, 'Name (optional)', name), submit),
    message);
  root.append(h('section', { class: 'card', 'aria-labelledby': 'up-h' }, h('h2', { id: 'up-h' }, 'Upload a CSV'), form));

  // ---- lists
  const datasets = h('div', null, loading('Loading datasets…'));
  const reports = h('div', null, loading('Loading reports…'));
  root.append(
    h('section', { class: 'card', 'aria-labelledby': 'ds-h' }, h('h2', { id: 'ds-h' }, 'Your datasets'), datasets),
    h('section', { class: 'card', 'aria-labelledby': 'rp-h' }, h('h2', { id: 'rp-h' }, 'Your reports'), reports));

  const loadDatasets = async () => {
    try {
      const list = await api('GET', '/api/datasets');
      clear(datasets).append(list.length ? h('ul', { class: 'cards' }, list.map((d) => h('li', null,
        h('a', { class: 'mini', href: `#/datasets/${d.id}` },
          h('strong', null, d.name),
          h('span', { class: 'muted' }, `${num(d.row_count)} rows · ${when(d.created_at)}`),
          d.rejected_count
            ? h('span', { class: 'badge warn' }, `${num(d.rejected_count)} rejected`)
            : h('span', { class: 'badge active' }, 'every row read')))))
        : empty('No datasets yet', 'Upload a CSV above to get started. Try sample_data/messy_sales.csv.'));
    } catch (err) { clear(datasets).append(errorBox(err)); }
  };

  const loadReports = async () => {
    try {
      const list = await api('GET', '/api/reports');
      clear(reports).append(list.length ? h('ul', { class: 'list' }, list.map((r) => h('li', null,
        h('span', null, h('a', { href: `#/reports/${r.id}` }, r.title),
          h('span', { class: 'muted' }, ` · from ${r.dataset_name} · updated ${when(r.updated_at)}`)),
        h('button', { class: 'btn small danger', type: 'button', 'aria-label': `Delete report ${r.title}`, onclick: async () => {
          if (!confirm(`Delete “${r.title}”? Its share links will stop working.`)) return;
          try { await api('DELETE', `/api/reports/${r.id}`); loadReports(); } catch (err) { clear(reports).append(errorBox(err)); }
        } }, 'Delete'))))
        : empty('No reports yet', 'Open a dataset and choose “Create a report”.'));
    } catch (err) { clear(reports).append(errorBox(err)); }
  };

  loadDatasets();
  loadReports();
}