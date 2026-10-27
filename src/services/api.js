const API_BASE_URL = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:5000').replace(/\/+$/, '');
const TOKEN_KEY = 'skillswap_access_token';

export class ApiError extends Error {
  constructor(message, status, payload = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

export function getStoredToken() {
  try {
    return window.sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function storeToken(token) {
  try {
    window.sessionStorage.setItem(TOKEN_KEY, token);
  } catch {
    throw new Error('This browser could not save the sign-in session. Check its storage settings and try again.');
  }
}

export function clearStoredToken() {
  try {
    window.sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // The in-memory auth state is still cleared if browser storage is unavailable.
  }
}

function responseMessage(payload, fallback) {
  if (typeof payload?.error === 'string') return payload.error;
  if (typeof payload?.error?.message === 'string') return payload.error.message;
  if (typeof payload?.message === 'string') return payload.message;
  return fallback;
}

export async function apiRequest(path, options = {}) {
  const { method = 'GET', body, auth = false, token, signal, headers: extraHeaders } = options;
  const accessToken = token || (auth ? getStoredToken() : null);
  const headers = { Accept: 'application/json', ...extraHeaders };
  const requestOptions = { method, headers, signal };

  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    requestOptions.body = JSON.stringify(body);
  }
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, requestOptions);
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiError('Could not reach SkillSwap. Check that the Flask server is running.', 0);
  }

  let payload = null;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    try { payload = await response.json(); } catch { payload = null; }
  }

  if (!response.ok) {
    if (response.status === 401 && accessToken) {
      window.dispatchEvent(new CustomEvent('skillswap:unauthorized'));
    }
    throw new ApiError(responseMessage(payload, `Request failed (${response.status})`), response.status, payload);
  }
  return payload;
}

export function buildQuery(values) {
  const query = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') query.set(key, value);
  });
  const text = query.toString();
  return text ? `?${text}` : '';
}
