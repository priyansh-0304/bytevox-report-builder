const nf = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
const compactNf = new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 });

export const num = (n) => (n == null ? '—' : nf.format(n));
export const compact = (n) => compactNf.format(n);
export const when = (secs) => new Date(secs * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
export const cell = (v) => (v == null ? '—' : typeof v === 'number' ? nf.format(v) : String(v));
export const plural = (n, one, many) => `${nf.format(n)} ${n === 1 ? one : many}`;
