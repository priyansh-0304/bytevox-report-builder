// Runs before the page paints (a plain, blocking script in <head>) so a saved theme never flashes the wrong colours.
try {
  const t = localStorage.getItem('theme');
  if (t === 'dark' || t === 'light') document.documentElement.dataset.theme = t;
} catch { /* storage blocked: follow the system setting */ }