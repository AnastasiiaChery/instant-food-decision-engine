// Admin analytics dashboard. Fetches /api/v1/admin/stats with the stored JWT and
// renders the aggregates from services/analytics.collect_stats. The endpoint 404s
// for anyone whose email isn't in ANALYTICS_ADMIN_EMAILS, so a non-admin (or a
// signed-out visitor) simply sees the "no access" panel — nothing is leaked.
import { getToken } from './utils.js';

const $ = (id) => document.getElementById(id);

// Build a DOM node with text content — never innerHTML, since some values
// (search mode, request paths) originate from client-posted event props.
function el(tag, opts = {}, children = []) {
  const node = document.createElement(tag);
  if (opts.class) node.className = opts.class;
  if (opts.text != null) node.textContent = String(opts.text);
  for (const child of children) node.append(child);
  return node;
}

function metricCard(label, value, sub) {
  return el('div', { class: 'card' }, [
    el('div', { class: 'card-value', text: value }),
    el('div', { class: 'card-label', text: label }),
    ...(sub != null ? [el('div', { class: 'card-sub', text: sub })] : []),
  ]);
}

function num(n) {
  return (n == null) ? '—' : Number(n).toLocaleString('en-US');
}

function ms(n) {
  return (n == null) ? '—' : `${num(n)} ms`;
}

function showState(which) {
  for (const id of ['loadingState', 'errorState', 'dashboard']) {
    $(id).style.display = (id === which) ? '' : 'none';
  }
}

function render(s) {
  // --- Audience ---
  const aud = $('audience');
  aud.replaceChildren(
    metricCard('DAU (24h)', num(s.audience?.dau)),
    metricCard('MAU (30d)', num(s.audience?.mau)),
    metricCard('Signups (7d)', num(s.audience?.signups_7d)),
  );

  // --- Funnel (7d) ---
  const f = s.funnel_7d || {};
  const funnel = $('funnel');
  const steps = [
    ['Visitors', f.visitors],
    ['Searched', f.searched],
    ['Got a result', f.got_result],
    ['Navigated', f.navigated],
  ];
  const top = Math.max(1, ...steps.map(([, v]) => v || 0));
  funnel.replaceChildren(...steps.map(([label, v]) => {
    const pct = Math.round(100 * (v || 0) / top);
    const bar = el('div', { class: 'bar' }, [
      el('div', { class: 'bar-fill' }),
    ]);
    bar.firstChild.style.width = `${pct}%`;
    return el('div', { class: 'funnel-row' }, [
      el('div', { class: 'funnel-label', text: label }),
      bar,
      el('div', { class: 'funnel-count', text: num(v) }),
    ]);
  }));
  $('funnelConv').textContent = `Search → navigate: ${f.search_to_navigate_pct ?? 0}%`;

  // --- Searches by mode (7d) ---
  const modes = s.searches_by_mode_7d || {};
  const modeWrap = $('modes');
  const entries = Object.entries(modes).sort((a, b) => b[1] - a[1]);
  modeWrap.replaceChildren(
    ...(entries.length
      ? entries.map(([m, c]) => el('div', { class: 'pill' }, [
          el('span', { class: 'pill-key', text: m }),
          el('span', { class: 'pill-val', text: num(c) }),
        ]))
      : [el('div', { class: 'muted', text: 'No searches in the last 7 days.' })]),
  );

  // --- Ops (24h) ---
  const ops = s.ops_24h || {};
  $('ops').replaceChildren(
    metricCard('Requests (24h)', num(ops.requests)),
    metricCard('5xx errors', num(ops.errors_5xx), `${ops.error_rate_pct ?? 0}% error rate`),
    metricCard('Search p50', ms(ops.search_p50_ms)),
    metricCard('Search p95', ms(ops.search_p95_ms)),
  );

  // --- Endpoints table ---
  const tbody = $('endpointsBody');
  const rows = ops.endpoints || [];
  tbody.replaceChildren(
    ...(rows.length
      ? rows.map((e) => el('tr', {}, [
          el('td', { text: e.path }),
          el('td', { class: 'right', text: num(e.count) }),
          el('td', { class: 'right', text: ms(e.p95_ms) }),
        ]))
      : [el('tr', {}, [
          (() => { const td = el('td', { class: 'muted', text: 'No request logs in the last 24 hours.' }); td.colSpan = 3; return td; })(),
        ])]),
  );

  $('generatedAt').textContent = s.generated_at
    ? `Generated ${new Date(s.generated_at).toLocaleString()}`
    : '';
}

async function load() {
  const token = getToken();
  if (!token) { showState('errorState'); return; }

  showState('loadingState');
  try {
    const res = await fetch('/api/v1/admin/stats', {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) { showState('errorState'); return; }
    render(await res.json());
    showState('dashboard');
  } catch (err) {
    console.error('Failed to load admin stats:', err);
    showState('errorState');
  }
}

$('refreshBtn').addEventListener('click', load);
load();
