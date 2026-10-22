// Tiny DOM helpers. Text is ALWAYS added with createTextNode / textContent, never innerHTML,
// so text from an uploaded file (even "<script>...") is displayed as plain text and never runs.

const PROPS = new Set(['value', 'checked', 'selected', 'disabled', 'hidden', 'open', 'readOnly']);

function addKids(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k == null || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
}

function build(el, attrs, kids) {
  let value;
  for (const [key, val] of Object.entries(attrs || {})) {
    if (val == null || val === false) continue;
    if (key === 'class') el.setAttribute('class', val);
    else if (key.startsWith('on') && typeof val === 'function') el.addEventListener(key.slice(2), val);
    else if (key === 'value') value = val;                 // set after children exist (needed for <select>)
    else if (PROPS.has(key)) el[key] = val;
    else el.setAttribute(key, val === true ? '' : val);
  }
  addKids(el, kids);
  if (value !== undefined) el.value = value;
  return el;
}

export const h = (tag, attrs, ...kids) => build(document.createElement(tag), attrs, kids);
export const s = (tag, attrs, ...kids) => build(document.createElementNS('http://www.w3.org/2000/svg', tag), attrs, kids);

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

/** Clears `node`, then fills it with `kids`. Unlike the built-in node.append(), null and false are
 *  skipped (the built-in would print the text "null"). */
export function mount(node, ...kids) {
  clear(node);
  addKids(node, kids);
  return node;
}