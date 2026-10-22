// One place that talks to the server. The browser only displays what the server computed.

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function messageFrom(body, status) {
  if (body && typeof body.detail === 'string') return body.detail;
  if (status === 401) return 'Please sign in.';
  if (status === 413) return 'The file is too large.';
  if (status === 429) return 'Too many requests. Please wait a few minutes and try again.';
  return `Something went wrong (error ${status}). Please try again.`;
}

export async function api(method, path, body, { quiet = false } = {}) {
  const opts = { method, headers: {}, credentials: 'same-origin' };
  if (body instanceof FormData) {
    opts.body = body;                                       // browser sets the multipart boundary
  } else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch {
    throw new ApiError(0, 'Could not reach the server. Check your connection and try again.');
  }
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON error body */ }
  if (!res.ok) {
    if (res.status === 401 && !quiet) window.dispatchEvent(new Event('session-expired'));
    throw new ApiError(res.status, messageFrom(data, res.status));
  }
  return data;
}

/** Upload with a progress callback (fetch cannot report upload progress, XMLHttpRequest can).
 *  onProgress receives a number from 0 to 1. Errors look exactly like api() errors. */
export function apiUpload(path, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', path);
    xhr.responseType = 'json';
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) return resolve(xhr.response);
      if (xhr.status === 401) window.dispatchEvent(new Event('session-expired'));
      reject(new ApiError(xhr.status, messageFrom(xhr.response, xhr.status)));
    };
    xhr.onerror = () => reject(new ApiError(0, 'Could not reach the server. Check your connection and try again.'));
    xhr.send(formData);
  });
}