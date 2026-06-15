import { state } from './state.js';
import { authHeaders } from './utils.js';
import { setStatus, useProfile } from './ui.js';
import { getLocation, consumeSSE } from './api.js';
import { placeUserPin, showMapTrigger, clearMarkers } from './map.js';
import { renderRecommendation } from './render.js';
import { t, getLang } from './i18n.js';
import { track } from './analytics.js';

export async function doAutopilot() {
  const btn = document.getElementById('autopilotBtn');
  btn.disabled = true;
  const cardsGrid = document.getElementById('cardsGrid');
  cardsGrid.innerHTML = '';
  state.cardMap.clear();
  clearMarkers();
  showMapTrigger(0);
  setStatus(t('status.requestingLocation'), 'loading');

  let lat, lng;
  try { ({ lat, lng } = await getLocation()); }
  catch (err) { setStatus(err.message, 'error'); btn.disabled = false; return; }
  placeUserPin(lat, lng);
  state.lastSearchLocation = { lat, lng };
  track('search_started', { mode: 'autopilot', lang: getLang() });

  try {
    const res = await fetch('/api/v1/search', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        mode: 'autopilot', lat, lng, use_profile: useProfile(), lang: getLang(),
        ...(state.autopilotSeen.length ? { exclude_place_names: state.autopilotSeen } : {}),
      }),
    });
    if (!res.ok) { setStatus(t('status.error', { code: res.status }), 'error'); btn.disabled = false; return; }

    await consumeSSE(res, (evType, payload) => {
      if (evType === 'searching') {
        setStatus(t('status.searchingNearby', { radius: payload.radius_m ? ` (${payload.radius_m}m)` : '' }), 'loading');
      } else if (evType === 'places') {
        const places = payload.places || payload;
        setStatus(t('status.analysing', { count: places.length }), 'loading');
        track('places_shown', { mode: 'autopilot', count: places.length });
      } else if (evType === 'recommendation') {
        const name = payload.place?.name;
        if (name && !state.autopilotSeen.includes(name)) state.autopilotSeen.push(name);
        renderRecommendation(payload, true, doAutopilot);
        setStatus(t('status.yourPlace'), 'done');
        track('recommendation_shown', { mode: 'autopilot' });
      } else if (evType === 'no_match') {
        setStatus(t('status.noMatchAutopilot'), 'error');
      } else if (evType === 'error') {
        setStatus(payload.detail || t('status.somethingWrong'), 'error');
      }
    });
  } catch (err) {
    setStatus(t('status.errorMsg', { message: err.message }), 'error');
  } finally {
    btn.disabled = false;
  }
}
