// Light/dark switch. With no saved choice the page follows the system setting (CSS media query);
// the button stores an explicit choice in localStorage (wrapped in try/catch: storage can be blocked).
const root = document.documentElement;

export const currentTheme = () =>
  root.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');

export function toggleTheme() {
  const next = currentTheme() === 'dark' ? 'light' : 'dark';
  root.dataset.theme = next;
  try { localStorage.setItem('theme', next); } catch { /* choice lasts for this page view only */ }
  return next;
}