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

let drawerLiked    = [];
let drawerDisliked = [];

function renderTagChips(containerId, tags, listRef) {
  const el = document.getElementById(containerId);
  el.innerHTML = '';
  tags.forEach((tag, i) => {
    const chip = document.createElement('div');
    chip.className = 'drawer-chip active';
    chip.textContent = tag + ' ✕';
    chip.addEventListener('click', () => {
      listRef.splice(i, 1);
      renderTagChips(containerId, listRef, listRef);
      updateSaveBtn();
    });
    el.appendChild(chip);
  });
}

function addTag(inputId, list, containerId) {
  const input = document.getElementById(inputId);
  const val   = input.value.trim();
  if (!val || list.includes(val)) { input.value = ''; return; }
  list.push(val);
  input.value = '';
  renderTagChips(containerId, list, list);
  updateSaveBtn();
}

let drawerInitialState = null;

function getDrawerCurrentState() {
  return {
    name:     document.getElementById('drawerDisplayName').value.trim(),
    diet:     [...document.querySelectorAll('#drawerDietChips .drawer-chip.active')].map(c => c.dataset.diet).sort().join(','),
    liked:    [...drawerLiked].sort().join(','),
    disliked: [...drawerDisliked].sort().join(','),
  };
}

function updateSaveBtn() {
  const btn = document.getElementById('drawerSaveBtn');
  if (!btn) return;
  if (!drawerInitialState) { btn.disabled = true; return; }
  const cur = getDrawerCurrentState();
  btn.disabled = cur.name     === drawerInitialState.name &&
                 cur.diet     === drawerInitialState.diet &&
                 cur.liked    === drawerInitialState.liked &&
                 cur.disliked === drawerInitialState.disliked;
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
    } else if (meRes.status !== 404) {
      serverError = true;
    }

    if (prefRes.ok) {
      const prefs = await prefRes.json();
      document.querySelectorAll('#drawerDietChips .drawer-chip').forEach(chip => {
        chip.classList.toggle('active', (prefs.diet || []).includes(chip.dataset.diet));
      });
      drawerLiked    = [...(prefs.cuisines_liked    || [])];
      drawerDisliked = [...(prefs.cuisines_disliked || [])];
      renderTagChips('drawerCuisinesLiked',    drawerLiked,    drawerLiked);
      renderTagChips('drawerCuisinesDisliked', drawerDisliked, drawerDisliked);
    } else if (prefRes.status !== 404) {
      serverError = true;
    }
  } catch { serverError = true; }

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

document.getElementById('drawerCuisineLikedAdd').addEventListener('click', () => addTag('drawerCuisineLikedInput', drawerLiked, 'drawerCuisinesLiked'));
document.getElementById('drawerCuisineDislikedAdd').addEventListener('click', () => addTag('drawerCuisineDislikedInput', drawerDisliked, 'drawerCuisinesDisliked'));
document.getElementById('drawerCuisineLikedInput').addEventListener('keydown', e => { if (e.key === 'Enter') addTag('drawerCuisineLikedInput', drawerLiked, 'drawerCuisinesLiked'); });
document.getElementById('drawerCuisineDislikedInput').addEventListener('keydown', e => { if (e.key === 'Enter') addTag('drawerCuisineDislikedInput', drawerDisliked, 'drawerCuisinesDisliked'); });

document.getElementById('drawerDisplayName').addEventListener('input', updateSaveBtn);
document.querySelectorAll('#drawerDietChips .drawer-chip').forEach(chip => {
  chip.addEventListener('click', () => { chip.classList.toggle('active'); updateSaveBtn(); });
});

document.getElementById('drawerSaveBtn').addEventListener('click', async () => {
  const btn         = document.getElementById('drawerSaveBtn');
  btn.disabled      = true;
  const displayName = document.getElementById('drawerDisplayName').value.trim();
  const diet        = [...document.querySelectorAll('#drawerDietChips .drawer-chip.active')].map(c => c.dataset.diet);
  try {
    await Promise.all([
      fetch('/api/v1/profile/me', {
        method: 'PUT', headers: authHeaders(),
        body: JSON.stringify({ display_name: displayName }),
      }),
      fetch('/api/v1/profile/preferences', {
        method: 'PUT', headers: authHeaders(),
        body: JSON.stringify({ diet, cuisines_liked: drawerLiked, cuisines_disliked: drawerDisliked }),
      }),
    ]);
    const newName   = displayName || document.getElementById('drawerEmail').value;
    document.getElementById('drawerUserName').textContent = newName || t('drawer.user');
    const avatarBtn = document.getElementById('avatarBtn');
    if (avatarBtn && newName) avatarBtn.textContent = newName[0].toUpperCase();
    drawerInitialState = getDrawerCurrentState();
    btn.textContent = t('drawer.saved');
    setTimeout(() => { btn.textContent = t('drawer.save'); updateSaveBtn(); }, 1500);
  } catch { updateSaveBtn(); }
});
