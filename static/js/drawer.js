import { authHeaders, escHtml, safeUrl, parseJwt, getToken } from './utils.js';
import { t } from './i18n.js';

export function openDrawer() {
  const token = getToken();
  if (!token) return;
  const p = parseJwt(token) || {};
  document.getElementById('drawerUserName').textContent  = p.display_name || p.email || t('drawer.user');
  document.getElementById('drawerUserEmail').textContent = p.email || '';
  document.getElementById('drawerDisplayName').value     = p.display_name || '';
  document.getElementById('drawerEmail').value           = p.email || '';
  document.getElementById('userDrawer').classList.add('open');
  document.body.style.overflow = 'hidden';
  switchDrawerTab('profile');
  loadDrawerProfile();
}

export function closeDrawer() {
  document.getElementById('userDrawer').classList.remove('open');
  document.body.style.overflow = '';
}

function switchDrawerTab(tab) {
  document.querySelectorAll('.drawer-tab').forEach(t => t.classList.toggle('active', t.dataset.drawertab === tab));
  document.getElementById('drawerPanelProfile').style.display = tab === 'profile' ? '' : 'none';
  document.getElementById('drawerPanelHistory').style.display = tab === 'history' ? '' : 'none';
  if (tab === 'history') loadDrawerHistory();
}

// ── Taste-profile chip groups ────────────────────────────────────────────────
// Each group maps a DOM container of `.drawer-chip[data-val]` to a preferences
// key. `multi` groups allow any number of active chips (stored as a list);
// single-select groups store one slug or null. The markup is the single source
// of truth for which chips exist (see index.html / profile_setup.html).
const PREF_GROUPS = [
  { id: 'drawerDietChips',    key: 'diet',           multi: true  },
  { id: 'drawerSpiceChips',   key: 'spice',          multi: false },
  { id: 'drawerStyleChips',   key: 'adventure',      multi: false },
  { id: 'drawerCuisineChips', key: 'cuisines_liked', multi: true  },
  { id: 'drawerAvoidChips',   key: 'avoid',          multi: true  },
  { id: 'drawerDrinksChips',  key: 'drinks',         multi: true  },
];

// Legacy free-text dislikes are no longer editable here, but we round-trip them
// on save so a returning user's existing data isn't wiped.
let drawerLegacyDisliked = [];

// Last-loaded values, used to revert on Cancel and to re-render the read-only
// "about me" summary (view mode shows only the chips the user actually picked).
let loadedPrefs = {};
let loadedName  = '';

function wirePrefChips() {
  PREF_GROUPS.forEach(g => {
    const container = document.getElementById(g.id);
    if (!container) return;
    container.querySelectorAll('.drawer-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        if (g.multi) {
          chip.classList.toggle('active');
        } else {
          const wasActive = chip.classList.contains('active');
          container.querySelectorAll('.drawer-chip').forEach(c => c.classList.remove('active'));
          if (!wasActive) chip.classList.add('active');
        }
        updateSaveBtn();
      });
    });
  });
}

function applyPrefsToChips(prefs) {
  PREF_GROUPS.forEach(g => {
    const container = document.getElementById(g.id);
    if (!container) return;
    const val = prefs[g.key];
    const selected = g.multi ? (val || []) : (val ? [val] : []);
    container.querySelectorAll('.drawer-chip').forEach(chip => {
      chip.classList.toggle('active', selected.includes(chip.dataset.val));
    });
  });
}

function readPrefsFromChips() {
  const out = {};
  PREF_GROUPS.forEach(g => {
    const container = document.getElementById(g.id);
    if (!container) return;
    const active = [...container.querySelectorAll('.drawer-chip.active')].map(c => c.dataset.val);
    out[g.key] = g.multi ? active : (active[0] || null);
  });
  out.cuisines_disliked = drawerLegacyDisliked;
  return out;
}

// ── View vs edit mode ────────────────────────────────────────────────────────
// View mode shows ONLY the chips the user selected (a compact "about me"
// summary) and hides empty sections. Edit mode reveals the full catalog so the
// user can re-pick or reset. The CSS keys off `.mode-view` / `.mode-edit`.
function refreshViewMode() {
  let any = false;
  document.querySelectorAll('#drawerPanelProfile .pref-section').forEach(sec => {
    const n = sec.querySelectorAll('.drawer-chip.active').length;
    sec.classList.toggle('is-empty', n === 0);
    if (n > 0) any = true;
  });
  const hint = document.getElementById('drawerPrefsHint');
  if (hint) hint.style.display = any ? 'none' : '';
}

function setMode(mode) {
  const panel     = document.getElementById('drawerPanelProfile');
  const editBtn   = document.getElementById('drawerEditBtn');
  const nameInput = document.getElementById('drawerDisplayName');
  const editing   = mode === 'edit';
  panel.classList.toggle('mode-edit', editing);
  panel.classList.toggle('mode-view', !editing);
  if (editBtn) editBtn.textContent = editing ? t('drawer.cancel') : t('drawer.edit');
  if (nameInput) nameInput.toggleAttribute('readonly', !editing);
  if (!editing) refreshViewMode();
}

let drawerInitialState = null;

function getDrawerCurrentState() {
  const prefs = readPrefsFromChips();
  const snapshot = PREF_GROUPS.map(g => {
    const v = prefs[g.key];
    return Array.isArray(v) ? [...v].sort().join(',') : (v || '');
  }).join('|');
  return {
    name:  document.getElementById('drawerDisplayName').value.trim(),
    prefs: snapshot,
  };
}

function updateSaveBtn() {
  const btn = document.getElementById('drawerSaveBtn');
  if (!btn) return;
  if (!drawerInitialState) { btn.disabled = true; return; }
  const cur = getDrawerCurrentState();
  btn.disabled = cur.name === drawerInitialState.name && cur.prefs === drawerInitialState.prefs;
}

async function loadDrawerProfile() {
  const statusEl = document.getElementById('drawerProfileStatus');
  drawerInitialState = null;
  updateSaveBtn();
  if (statusEl) statusEl.textContent = '';

  let serverError = false;
  try {
    const [meRes, prefRes] = await Promise.all([
      fetch('/api/v1/profile/me',          { headers: authHeaders() }),
      fetch('/api/v1/profile/preferences', { headers: authHeaders() }),
    ]);

    if (meRes.ok) {
      const me = await meRes.json();
      document.getElementById('drawerUserName').textContent  = me.display_name || me.email || t('drawer.user');
      document.getElementById('drawerUserEmail').textContent = me.email || '';
      document.getElementById('drawerDisplayName').value     = me.display_name || '';
      document.getElementById('drawerEmail').value           = me.email || '';
      loadedName = me.display_name || '';
    } else if (meRes.status !== 404) {
      serverError = true;
    }

    if (prefRes.ok) {
      const prefs = await prefRes.json();
      loadedPrefs = prefs;
      drawerLegacyDisliked = [...(prefs.cuisines_disliked || [])];
      applyPrefsToChips(prefs);
    } else if (prefRes.status !== 404) {
      serverError = true;
    }
  } catch { serverError = true; }

  setMode('view');

  if (statusEl && serverError) {
    statusEl.textContent = t('drawer.serverError');
    statusEl.style.color = '#ef4444';
  }

  drawerInitialState = getDrawerCurrentState();
  updateSaveBtn();
}

function relativeTime(isoStr) {
  const diff = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return t('drawer.timeAgoMin', { n: mins });
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return t('drawer.timeAgoHour', { n: hrs });
  return t('drawer.timeAgoDay', { n: Math.floor(hrs / 24) });
}

async function loadDrawerHistory() {
  const el = document.getElementById('drawerHistoryContent');
  el.innerHTML = `<div class="history-empty">${escHtml(t('drawer.loading'))}</div>`;
  try {
    const res = await fetch('/api/v1/history', { headers: authHeaders() });
    if (!res.ok && res.status !== 404) {
      el.innerHTML = `<div class="history-empty">${escHtml(t('drawer.historyError'))}</div>`;
      return;
    }
    const entries = res.ok ? await res.json() : [];
    const favs    = entries.filter(e => e.action_type === 'favorite');
    const navs    = entries.filter(e => e.action_type === 'navigate');

    el.innerHTML = '';

    function renderSection(title, icon, list) {
      const titleEl = document.createElement('div');
      titleEl.className = 'history-section-title';
      titleEl.innerHTML = `${icon} ${title} <span style="color:var(--text-3);font-weight:400">(${list.length})</span>`;
      el.appendChild(titleEl);
      if (!list.length) {
        const empty = document.createElement('div');
        empty.className = 'history-empty';
        empty.style.padding = '8px 0 16px';
        empty.textContent = t('drawer.nothingHere');
        el.appendChild(empty);
        return;
      }
      list.forEach(e => {
        const entry = document.createElement('div');
        entry.className = 'history-entry';
        entry.innerHTML = `
          <div class="history-entry-name">${escHtml(e.place_name)}</div>
          <div class="history-entry-meta">${escHtml(e.place_type)} · ${escHtml(relativeTime(e.chosen_at))}</div>
          <a class="history-entry-nav" href="${escHtml(safeUrl(e.nav_url))}" target="_blank" rel="noopener noreferrer">Navigate →</a>
        `;
        el.appendChild(entry);
      });
    }

    renderSection(t('drawer.favourites'), '♥', favs);
    renderSection(t('drawer.navigated'), '🧭', navs);
  } catch { el.innerHTML = `<div class="history-empty">${escHtml(t('drawer.historyError'))}</div>`; }
}

// Event listeners
document.getElementById('drawerClose').addEventListener('click', closeDrawer);
document.getElementById('drawerBackdrop').addEventListener('click', closeDrawer);
document.querySelectorAll('.drawer-tab').forEach(t => t.addEventListener('click', () => switchDrawerTab(t.dataset.drawertab)));

document.getElementById('drawerDisplayName').addEventListener('input', updateSaveBtn);
wirePrefChips();

document.getElementById('drawerEditBtn').addEventListener('click', () => {
  const editing = document.getElementById('drawerPanelProfile').classList.contains('mode-edit');
  if (editing) {
    // Cancel → revert to last-loaded values.
    applyPrefsToChips(loadedPrefs);
    document.getElementById('drawerDisplayName').value = loadedName;
    drawerInitialState = getDrawerCurrentState();
    updateSaveBtn();
    setMode('view');
  } else {
    setMode('edit');
  }
});

document.getElementById('drawerResetBtn').addEventListener('click', () => {
  document.querySelectorAll('#drawerPanelProfile .pref-section .drawer-chip.active')
    .forEach(c => c.classList.remove('active'));
  updateSaveBtn();
});

document.getElementById('drawerSaveBtn').addEventListener('click', async () => {
  const btn         = document.getElementById('drawerSaveBtn');
  btn.disabled      = true;
  const displayName = document.getElementById('drawerDisplayName').value.trim();
  const prefs       = readPrefsFromChips();
  try {
    await Promise.all([
      fetch('/api/v1/profile/me', {
        method: 'PUT', headers: authHeaders(),
        body: JSON.stringify({ display_name: displayName }),
      }),
      fetch('/api/v1/profile/preferences', {
        method: 'PUT', headers: authHeaders(),
        body: JSON.stringify(prefs),
      }),
    ]);
    const newName   = displayName || document.getElementById('drawerEmail').value;
    document.getElementById('drawerUserName').textContent = newName || t('drawer.user');
    const avatarBtn = document.getElementById('avatarBtn');
    if (avatarBtn && newName) avatarBtn.textContent = newName[0].toUpperCase();
    // Persisted values become the new baseline, then collapse back to the summary.
    loadedPrefs = readPrefsFromChips();
    loadedName  = displayName;
    drawerInitialState = getDrawerCurrentState();
    btn.textContent = t('drawer.saved');
    setTimeout(() => { btn.textContent = t('drawer.save'); updateSaveBtn(); setMode('view'); }, 900);
  } catch { updateSaveBtn(); }
});
