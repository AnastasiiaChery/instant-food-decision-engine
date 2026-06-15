import { getToken } from './utils.js';
import { t } from './i18n.js';

const GEO_CONSENT_KEY = 'instantfood_geo_consent';

// Ask for informed consent once, before the browser's own permission prompt, so the
// user knows why we need their location and where it goes (GDPR transparency).
// Resolves when the user accepts (now or previously); rejects if they decline.
function ensureGeoConsent() {
  return new Promise((resolve, reject) => {
    if (localStorage.getItem(GEO_CONSENT_KEY) === '1') { resolve(); return; }
    const modal  = document.getElementById('geoConsentModal');
    const okBtn   = document.getElementById('geoConsentOk');
    const cancel  = document.getElementById('geoConsentCancel');
    if (!modal || !okBtn || !cancel) { resolve(); return; } // fail open if markup missing

    const close = () => {
      modal.classList.remove('open');
      okBtn.removeEventListener('click', onOk);
      cancel.removeEventListener('click', onCancel);
    };
    const onOk = () => { localStorage.setItem(GEO_CONSENT_KEY, '1'); close(); resolve(); };
    const onCancel = () => { close(); reject(new Error(t('geo.consentDeclined'))); };

    okBtn.addEventListener('click', onOk);
    cancel.addEventListener('click', onCancel);
    modal.classList.add('open');
  });
}

export async function getLocation() {
  await ensureGeoConsent();
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) { reject(new Error(t('geo.notSupported'))); return; }
    navigator.geolocation.getCurrentPosition(
      p => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
      e => {
        if (e.code === 1) reject(new Error(t('geo.denied')));
        else if (e.code === 2) reject(new Error(t('geo.unavailable')));
        else reject(new Error(t('geo.timeout')));
      },
      { enableHighAccuracy: false, timeout: 30000, maximumAge: 300000 },
    );
  });
}

export async function consumeSSE(res, onEvent) {
  const reader = res.body.getReader();
  const dec    = new TextDecoder();
  let buf = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const chunks = buf.split('\n\n');
    buf = chunks.pop();
    for (const chunk of chunks) {
      if (!chunk.trim()) continue;
      let evType = 'message', dataLine = '';
      for (const line of chunk.split('\n')) {
        if (line.startsWith('event: ')) evType = line.slice(7).trim();
        else if (line.startsWith('data: ')) dataLine = line.slice(6);
      }
      if (!dataLine) continue;
      try { onEvent(evType, JSON.parse(dataLine)); } catch (_) {}
    }
  }
}

export function recordNavigate(place) {
  const token = getToken();
  if (!token) return;
  fetch('/api/v1/history/navigate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      place_name: place.name,
      place_type: place.amenity || 'restaurant',
      lat: place.lat,
      lng: place.lon,
    }),
  }).catch(() => {});
}
