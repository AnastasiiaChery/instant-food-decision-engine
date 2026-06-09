export const TOKEN_KEY     = 'instantfood_token';
export const ONBOARDED_KEY = 'instantfood_onboarded';

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = t  => localStorage.setItem(TOKEN_KEY, t);

export function parseJwt(token) {
  try {
    const b64    = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = b64.padEnd(b64.length + (4 - b64.length % 4) % 4, '=');
    return JSON.parse(atob(padded));
  } catch (_) { return null; }
}

export function isTokenValid(token) {
  const p = parseJwt(token);
  return p ? p.exp * 1000 > Date.now() : false;
}

export function escHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function safeUrl(url) {
  try {
    const u = new URL(url);
    return (u.protocol === 'https:' || u.protocol === 'http:') ? url : '#';
  } catch { return '#'; }
}

export function authHeaders() {
  const t = getToken();
  return t
    ? { 'Content-Type': 'application/json', Authorization: `Bearer ${t}` }
    : { 'Content-Type': 'application/json' };
}
