import { state } from './state.js';
import { authHeaders } from './utils.js';
import { setStatus, useProfile } from './ui.js';
import { getLocation, consumeSSE } from './api.js';
import { placeUserPin, showMapTrigger, clearMarkers } from './map.js';
import { renderRecommendation } from './render.js';

export async function doAutopilot() {
  const btn = document.getElementById('autopilotBtn');
  btn.disabled = true;
  const cardsGrid = document.getElementById('cardsGrid');
  cardsGrid.innerHTML = '';
  state.cardMap.clear();
  clearMarkers();
  showMapTrigger(0);
  setStatus('Requesting location…', 'loading');

  let lat, lng;
  try { ({ lat, lng } = await getLocation()); }
  catch (err) { setStatus(err.message, 'error'); btn.disabled = false; return; }
  placeUserPin(lat, lng);

  try {
    const res = await fetch('/api/v1/search', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        mode: 'autopilot', lat, lng, use_profile: useProfile(),
        ...(state.lastAutopilotPlace ? { exclude_place_name: state.lastAutopilotPlace } : {}),
      }),
    });
    if (!res.ok) { setStatus(`Error ${res.status}`, 'error'); btn.disabled = false; return; }

    await consumeSSE(res, (evType, payload) => {
      if (evType === 'searching') {
        setStatus(`Searching nearby${payload.radius_m ? ` (${payload.radius_m}m)` : ''}…`, 'loading');
      } else if (evType === 'places') {
        const places = payload.places || payload;
        setStatus(`Analysing ${places.length} candidates…`, 'loading');
      } else if (evType === 'recommendation') {
        state.lastAutopilotPlace = payload.place?.name || null;
        renderRecommendation(payload, true, doAutopilot);
        setStatus("Here's your place", 'done');
      } else if (evType === 'no_match') {
        setStatus('No matching places found — try a wider radius or different query.', 'error');
      } else if (evType === 'error') {
        setStatus(payload.detail || 'Something went wrong.', 'error');
      }
    });
  } catch (err) {
    setStatus(`Error: ${err.message}`, 'error');
  } finally {
    btn.disabled = false;
  }
}
