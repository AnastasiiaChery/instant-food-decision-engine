import { state } from './state.js';
import { setStatus } from './ui.js';
import { clearMarkers, showMapTrigger } from './map.js';
import { initAuth, openAuthModal } from './auth.js';
import { doAutopilot } from './autopilot.js';
import { doPlan } from './plan.js';
import { initI18n, setLang, getLang, t, AVAILABLE_LANGS } from './i18n.js';

function switchMode(mode) {
  state.currentMode = mode;
  document.querySelectorAll('.mode-tab, .htab').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  document.querySelectorAll('.mode-panel').forEach(p => p.classList.remove('active'));
  document.getElementById('panel-' + mode).classList.add('active');
  document.getElementById('cardsGrid').innerHTML = '';
  state.cardMap.clear();
  clearMarkers();
  state.autopilotSeen      = [];
  state.recFallback        = null;
  showMapTrigger(0);
  setStatus(t('status.ready'));
}

document.querySelectorAll('.mode-tab, .htab').forEach(b => {
  b.addEventListener('click', () => switchMode(b.dataset.mode));
});

document.getElementById('autopilotBtn').addEventListener('click', doAutopilot);
document.getElementById('planBtn').addEventListener('click', doPlan);

// --- Language switcher ---
function buildLangDropdown() {
  const dropdown = document.getElementById('langDropdown');
  const current  = getLang();
  document.getElementById('langCurrent').textContent = current;
  dropdown.innerHTML = '';
  AVAILABLE_LANGS.forEach(({ code, native }) => {
    const item = document.createElement('button');
    item.className = 'lang-dd-item' + (code === current ? ' active' : '');
    item.textContent = native;
    item.addEventListener('click', async () => {
      dropdown.style.display = 'none';
      if (code !== getLang()) await setLang(code);
    });
    dropdown.appendChild(item);
  });
}

const langBtn      = document.getElementById('langBtn');
const langDropdown = document.getElementById('langDropdown');
langBtn.addEventListener('click', e => {
  e.stopPropagation();
  langDropdown.style.display = langDropdown.style.display === 'none' ? 'block' : 'none';
});
document.addEventListener('click', () => { langDropdown.style.display = 'none'; });
document.addEventListener('i18n:changed', buildLangDropdown);
buildLangDropdown();

initAuth();

document.getElementById('landingRegisterBtn')?.addEventListener('click', () => openAuthModal('register'));
document.getElementById('landingSignInBtn')?.addEventListener('click', () => openAuthModal('login'));

// Load translations in the background. The HTML ships with English defaults, so
// the UI is fully interactive immediately; non-English dictionaries swap in when
// ready (and `i18n:changed` refreshes the language dropdown). Wiring the UI must
// NOT wait on this — a slow first-time translation would otherwise freeze every
// button until the fetch returns.
initI18n();
