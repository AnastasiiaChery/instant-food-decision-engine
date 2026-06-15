// First-party analytics client.
//
// Sends small batches of behaviour events to our own /api/v1/events endpoint —
// no third-party tracker, no cookies, no cross-site identifiers. Identity is a
// random anon_id kept in localStorage (pseudonymous; lets us count returning
// visitors and the pre-login funnel). When the user is logged in the request
// carries the JWT, so the backend links the event to their account server-side.
import { getToken } from './utils.js';

const ANON_KEY     = 'nompilot_anon_id';
const SESSION_KEY  = 'nompilot_session';
const SESSION_TTL  = 30 * 60 * 1000;   // 30 min of inactivity ends a session
const FLUSH_MS     = 4000;             // batch window — coalesce bursts of events

function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  // Fallback for older browsers without crypto.randomUUID.
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

function getAnonId() {
  let id = localStorage.getItem(ANON_KEY);
  if (!id) { id = uuid(); localStorage.setItem(ANON_KEY, id); }
  return id;
}

// A session id that rolls over after 30 min of inactivity. Stored with a
// last-seen timestamp so a returning visitor the next day starts a fresh session.
function getSessionId() {
  const now = Date.now();
  let raw;
  try { raw = JSON.parse(sessionStorage.getItem(SESSION_KEY) || 'null'); } catch { raw = null; }
  if (!raw || (now - raw.seen) > SESSION_TTL) {
    raw = { id: uuid(), seen: now };
  } else {
    raw.seen = now;
  }
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(raw));
  return raw.id;
}

let queue = [];
let flushTimer = null;

function flush(useBeacon = false) {
  if (!queue.length) return;
  const body = JSON.stringify({ anon_id: getAnonId(), events: queue });
  queue = [];
  clearTimeout(flushTimer);
  flushTimer = null;

  // On page hide we must use sendBeacon — a normal fetch would be killed as the
  // page unloads. During the session a keepalive fetch lets us attach the JWT so
  // events get linked to the account.
  if (useBeacon && navigator.sendBeacon) {
    navigator.sendBeacon('/api/v1/events', new Blob([body], { type: 'application/json' }));
    return;
  }
  const token = getToken();
  fetch('/api/v1/events', {
    method: 'POST',
    headers: token
      ? { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }
      : { 'Content-Type': 'application/json' },
    body,
    keepalive: true,
  }).catch(() => {});  // analytics is best-effort — never surface errors to the user
}

export function track(name, props = {}) {
  queue.push({
    name,
    session_id: getSessionId(),
    path: location.pathname,
    props: props || {},
  });
  // Batch cap matches the backend's per-request limit; flush early if we hit it.
  if (queue.length >= 20) { flush(); return; }
  if (!flushTimer) flushTimer = setTimeout(() => flush(), FLUSH_MS);
}

export function initAnalytics() {
  track('page_view');
  // Flush whatever is buffered before the page goes away (tab close, navigation,
  // backgrounding on mobile). visibilitychange is the reliable mobile signal.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush(true);
  });
  window.addEventListener('pagehide', () => flush(true));
}
