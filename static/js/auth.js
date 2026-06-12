import { TOKEN_KEY, ONBOARDED_KEY, getToken, setToken, parseJwt, isTokenValid } from './utils.js';
import { openDrawer } from './drawer.js';
import { t } from './i18n.js';

export function openAuthModal(tab) {
  document.getElementById('authModal').classList.add('open');
  document.body.style.overflow = 'hidden';
  document.getElementById('authError').textContent = '';
  switchAuthTab(tab || 'login');
}

export function closeAuthModal() {
  document.getElementById('authModal').classList.remove('open');
  document.body.style.overflow = '';
}

function switchAuthTab(tab) {
  document.querySelectorAll('.auth-tab').forEach(t => t.classList.toggle('active', t.dataset.authtab === tab));
  document.getElementById('authPanelLogin').style.display    = tab === 'login'    ? '' : 'none';
  document.getElementById('authPanelRegister').style.display = tab === 'register' ? '' : 'none';
  document.getElementById('authError').textContent = '';
}

async function handleAuthSuccess(token) {
  setToken(token);
  closeAuthModal();
  location.reload();
}

export function initAuth() {
  // Handle URL token from Google OAuth callback
  const urlParams = new URLSearchParams(location.search);
  const urlToken  = urlParams.get('token');
  if (urlToken) {
    setToken(urlToken);
    history.replaceState({}, '', '/');
    if (!localStorage.getItem(ONBOARDED_KEY)) {
      fetch('/api/v1/profile/preferences', { headers: { Authorization: `Bearer ${urlToken}` } })
        .then(r => r.ok ? r.json() : null)
        .then(prefs => {
          if (prefs && !prefs.diet?.length && !prefs.cuisines_liked?.length && !prefs.cuisines_disliked?.length) {
            location.replace('/profile/setup');
          } else {
            localStorage.setItem(ONBOARDED_KEY, '1');
          }
        })
        .catch(() => {});
    }
  }

  let token = getToken();
  if (token && !isTokenValid(token)) { localStorage.removeItem(TOKEN_KEY); token = null; }

  const authBtn   = document.getElementById('authBtn');
  const userMenu  = document.getElementById('userMenu');
  const avatarBtn = document.getElementById('avatarBtn');
  const dropdown  = document.getElementById('avatarDropdown');

  if (!token) {
    document.body.classList.add('is-guest');
    if (authBtn) { authBtn.removeAttribute('href'); authBtn.addEventListener('click', () => openAuthModal('login')); }
    return;
  }

  // Logged in: hide Sign in, show avatar menu
  if (authBtn) authBtn.style.display = 'none';
  if (userMenu) userMenu.style.display = 'flex';

  const p = parseJwt(token);
  if (p && avatarBtn) {
    const name = (p.display_name || p.email || '').trim();
    avatarBtn.textContent = name ? name[0].toUpperCase() : '?';
  }

  if (avatarBtn && dropdown) {
    avatarBtn.addEventListener('click', e => {
      e.stopPropagation();
      dropdown.style.display = dropdown.style.display !== 'none' ? 'none' : 'block';
    });
    document.addEventListener('click', () => { dropdown.style.display = 'none'; });
  }

  document.getElementById('ddProfile')?.addEventListener('click', () => {
    if (dropdown) dropdown.style.display = 'none';
    openDrawer();
  });
  document.getElementById('ddSignOut')?.addEventListener('click', () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(ONBOARDED_KEY);
    location.href = '/';
  });

  const toggleRow = document.getElementById('prefToggleRow');
  if (toggleRow) toggleRow.classList.add('visible');
}

// Auth modal event listeners (always active)
document.querySelectorAll('.auth-tab').forEach(t => t.addEventListener('click', () => switchAuthTab(t.dataset.authtab)));
document.getElementById('authModalClose').addEventListener('click', closeAuthModal);
document.getElementById('authModal').addEventListener('click', e => {
  if (e.target === document.getElementById('authModal')) closeAuthModal();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && document.getElementById('authModal').classList.contains('open')) closeAuthModal();
});

document.getElementById('loginSubmit').addEventListener('click', async () => {
  const email    = document.getElementById('loginEmail').value.trim();
  const password = document.getElementById('loginPassword').value;
  const errEl    = document.getElementById('authError');
  if (!email || !password) { errEl.textContent = t('auth.fillFields'); return; }
  const btn = document.getElementById('loginSubmit');
  btn.disabled = true;
  try {
    const res  = await fetch('/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!res.ok) { errEl.textContent = data.detail || t('auth.signInFailed'); return; }
    await handleAuthSuccess(data.token);
  } catch { errEl.textContent = t('auth.networkError'); }
  finally { btn.disabled = false; }
});

document.getElementById('registerSubmit').addEventListener('click', async () => {
  const name     = document.getElementById('registerName').value.trim() || null;
  const email    = document.getElementById('registerEmail').value.trim();
  const password = document.getElementById('registerPassword').value;
  const errEl    = document.getElementById('authError');
  if (!email || !password) { errEl.textContent = t('auth.emailPasswordRequired'); return; }
  if (password.length < 8)  { errEl.textContent = t('auth.passwordMin'); return; }
  const btn = document.getElementById('registerSubmit');
  btn.disabled = true;
  try {
    const res  = await fetch('/auth/register', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, display_name: name }),
    });
    const data = await res.json();
    if (!res.ok) { errEl.textContent = data.detail || t('auth.registrationFailed'); return; }
    // Fresh account → send straight into the taste questionnaire.
    setToken(data.token);
    closeAuthModal();
    location.replace('/profile/setup');
  } catch { errEl.textContent = t('auth.networkError'); }
  finally { btn.disabled = false; }
});
