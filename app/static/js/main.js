import { h, clear } from './dom.js';
import { api } from './api.js';
import { currentTheme, toggleTheme } from './theme.js';
import { authView } from './views/auth.js';
import { homeView } from './views/home.js';
import { datasetView } from './views/dataset.js';
import { reportView } from './views/report.js';
import { sharedView } from './views/shared.js';

const main = document.getElementById('main');
const nav = document.getElementById('nav');
let user = null;

function renderNav() {
  clear(nav).append(h('a', { class: 'brand', href: user ? '#/' : '/' }, 'Show-your-work reports'));
  const label = () => (currentTheme() === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
  const themeBtn = h('button', { class: 'btn small theme-btn', type: 'button', 'aria-label': label(), title: label(),
    onclick: () => { toggleTheme(); themeBtn.textContent = currentTheme() === 'dark' ? '☀' : '☾'; themeBtn.setAttribute('aria-label', label()); themeBtn.title = label(); } },
    currentTheme() === 'dark' ? '☀' : '☾');
  nav.append(themeBtn);
  if (user) {
    nav.append(h('span', { class: 'muted' }, user.email),
      h('button', { class: 'btn small', type: 'button', onclick: signOut }, 'Sign out'));
  }
}

async function signOut() {
  try { await api('POST', '/api/auth/logout', undefined, { quiet: true }); } catch { /* already signed out */ }
  user = null;
  location.hash = '';
  renderNav();
  showAuth();
}

function showAuth() {
  document.title = 'Sign in · Show-your-work reports';
  authView(main, (u) => { user = u; renderNav(); route(); });
}

function route() {
  if (!user) return showAuth();
  const m = location.hash.match(/^#\/(datasets|reports)\/(\d+)$/);
  if (m && m[1] === 'datasets') return datasetView(main, Number(m[2]));
  if (m && m[1] === 'reports') return reportView(main, Number(m[2]));
  return homeView(main);
}

async function boot() {
  const shared = location.pathname.match(/^\/s\/([A-Za-z0-9_-]+)$/);
  if (shared) {                       // public share page: no sign-in, no account calls
    renderNav();
    return sharedView(main, shared[1]);
  }
  window.addEventListener('session-expired', () => { user = null; renderNav(); showAuth(); });
  window.addEventListener('hashchange', () => { route(); window.scrollTo(0, 0); main.focus({ preventScroll: true }); });
  try { user = await api('GET', '/api/auth/me', undefined, { quiet: true }); } catch { user = null; }
  renderNav();
  route();
}

boot();
