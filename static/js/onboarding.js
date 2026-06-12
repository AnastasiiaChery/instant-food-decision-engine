// Standalone logic for the first-run taste questionnaire (/profile/setup).
// Deliberately does NOT import drawer.js — that module wires the in-app drawer
// at load time and its elements don't exist on this page. Chip groups are read
// generically via the `data-pref` / `data-multi` attributes on each container,
// so this stays in sync with the markup without a hard-coded field list.
import { t, initI18n } from './i18n.js';
import { getToken, isTokenValid, ONBOARDED_KEY, authHeaders } from './utils.js';

const token = getToken();
if (!token || !isTokenValid(token)) location.replace('/');

function groups() {
  return [...document.querySelectorAll('.drawer-chips[data-pref]')];
}

function wireChips() {
  groups().forEach(container => {
    const multi = container.hasAttribute('data-multi');
    container.querySelectorAll('.drawer-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        if (multi) {
          chip.classList.toggle('active');
        } else {
          const was = chip.classList.contains('active');
          container.querySelectorAll('.drawer-chip').forEach(c => c.classList.remove('active'));
          if (!was) chip.classList.add('active');
        }
      });
    });
  });
}

function readPrefs() {
  const out = {};
  groups().forEach(container => {
    const key    = container.dataset.pref;
    const multi  = container.hasAttribute('data-multi');
    const active = [...container.querySelectorAll('.drawer-chip.active')].map(c => c.dataset.val);
    out[key] = multi ? active : (active[0] || null);
  });
  return out;
}

function finish() {
  localStorage.setItem(ONBOARDED_KEY, '1');
  location.replace('/');
}

document.getElementById('onbSave').addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.textContent = t('onb.saving');
  try {
    await fetch('/api/v1/profile/preferences', {
      method: 'PUT', headers: authHeaders(), body: JSON.stringify(readPrefs()),
    });
  } catch { /* best-effort: still continue into the app */ }
  finish();
});

document.getElementById('onbSkip').addEventListener('click', finish);

wireChips();
initI18n();
