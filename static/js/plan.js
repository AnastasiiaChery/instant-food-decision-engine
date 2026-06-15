import { state } from './state.js';
import { authHeaders, escHtml } from './utils.js';
import { setStatus, useProfile } from './ui.js';
import { getLocation, consumeSSE } from './api.js';
import { initMap, openMap, closeMap, placeUserPin, showMapTrigger, clearMarkers } from './map.js';
import { renderPlanRecommendations } from './render.js';
import { t, getLang } from './i18n.js';
import { track } from './analytics.js';

export function setPlanLocation(lat, lng, label) {
  initMap();
  state.planCustomLocation = { lat, lng };
  document.getElementById('plan-loc-label').textContent = label;
  document.getElementById('plan-loc-set').classList.add('visible');
  if (state.planCustomMarker) state.planCustomMarker.remove();
  state.planCustomMarker = L.marker([lat, lng], {
    icon: L.divIcon({
      className: '',
      html: '<div style="width:14px;height:14px;border-radius:50%;background:var(--accent);border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.3)"></div>',
      iconSize: [14, 14], iconAnchor: [7, 7],
    }),
  }).addTo(state.map).bindPopup(label);
  state.map.flyTo([lat, lng], Math.max(state.map.getZoom(), 14), { animate: true, duration: 0.6 });
}

function clearPlanLocation() {
  state.planCustomLocation = null;
  if (state.planCustomMarker) { state.planCustomMarker.remove(); state.planCustomMarker = null; }
  document.getElementById('plan-loc-set').classList.remove('visible');
}

export async function doPlan() {
  const btn = document.getElementById('planBtn');
  btn.disabled = true;
  const cardsGrid = document.getElementById('cardsGrid');
  cardsGrid.innerHTML = '';
  state.cardMap.clear();
  clearMarkers();
  showMapTrigger(0);

  let lat, lng;
  if (state.planCustomLocation) {
    ({ lat, lng } = state.planCustomLocation);
    setStatus(t('status.planning'), 'loading');
  } else {
    setStatus(t('status.requestingLocation'), 'loading');
    try { ({ lat, lng } = await getLocation()); }
    catch (err) { setStatus(err.message, 'error'); btn.disabled = false; return; }
  }
  placeUserPin(lat, lng);
  state.lastSearchLocation = { lat, lng };

  let when = document.querySelector('.plan-chip[data-group="when"].active')?.dataset.val || 'now';
  if (when === 'custom') {
    const t = document.getElementById('planTimeInput').value;
    when = t || 'now';
  }
  const group     = document.querySelector('.plan-chip[data-group="group"].active')?.dataset.val  || 'solo';
  const budgetVal = document.querySelector('.plan-chip[data-group="budget"].active')?.dataset.val;
  const budget    = (budgetVal && budgetVal !== 'any') ? budgetVal : null;
  const query     = document.getElementById('planQuery').value.trim() || null;

  try {
    const body = {
      mode: 'plan', lat, lng, when, group_size: group, use_profile: useProfile(),
      lang: getLang(),
      radius_m: Math.round(parseFloat(document.getElementById('planRadiusSlider').value) * 1000),
      ...(budget ? { budget } : {}),
    };
    if (query) body.query = query;
    track('search_started', { mode: 'plan', lang: getLang(), group, has_query: !!query });

    const res = await fetch('/api/v1/search', {
      method: 'POST', headers: authHeaders(), body: JSON.stringify(body),
    });
    if (!res.ok) { setStatus(t('status.error', { code: res.status }), 'error'); btn.disabled = false; return; }

    await consumeSSE(res, (evType, payload) => {
      if (evType === 'searching') {
        setStatus(t('status.aiPlanning'), 'loading');
      } else if (evType === 'places') {
        setStatus(t('status.findingOptions'), 'loading');
        const places = payload.places || payload;
        track('places_shown', { mode: 'plan', count: Array.isArray(places) ? places.length : 0 });
      } else if (evType === 'planning') {
        setStatus(payload.message || t('status.planning'), 'loading');
      } else if (evType === 'recommendations') {
        renderPlanRecommendations(payload);
        const count = (payload.recommendations || []).length;
        track('recommendation_shown', { mode: 'plan', count });
        if (payload.notice) {
          setStatus(t(count === 1 ? 'status.alternative' : 'status.alternatives', { count }), 'warn');
        } else {
          setStatus(t('status.curatedOptions', { count }), 'done');
        }
      } else if (evType === 'no_match') {
        setStatus(t('status.noMatchPlan'), 'error');
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

// Radius slider
document.getElementById('planRadiusSlider').addEventListener('input', function () {
  document.getElementById('planRadiusVal').textContent = this.value + ' km';
});

// Plan chips (when / group / budget)
document.querySelectorAll('.plan-chip').forEach(chip => {
  chip.addEventListener('click', () => {
    const g = chip.dataset.group;
    document.querySelectorAll(`.plan-chip[data-group="${g}"]`).forEach(c => c.classList.remove('active'));
    chip.classList.add('active');

    if (g === 'when') {
      document.getElementById('custom-time-row').style.display = chip.dataset.val === 'custom' ? '' : 'none';
    }

    if (g === 'loc') {
      handleLocChip(chip.dataset.val);
    }
  });
});

// Map click handler registration (once, lazily)
let planClickHandlerRegistered = false;

function ensurePlanMapClick() {
  if (planClickHandlerRegistered) return;
  planClickHandlerRegistered = true;
  const map = initMap();
  map.on('click', e => {
    if (!state.planMapClickActive) return;
    const { lat, lng } = e.latlng;
    setPlanLocation(lat, lng, `${lat.toFixed(4)}, ${lng.toFixed(4)}`);
    state.planMapClickActive = false;
    const mt = document.querySelector('.map-title');
    if (mt) mt.textContent = t('map.nearbyPlaces');
    closeMap();
  });
}

function handleLocChip(val) {
  document.getElementById('plan-addr-wrap').classList.toggle('visible', val === 'address');
  document.getElementById('plan-map-hint').classList.toggle('visible', val === 'map');
  state.planMapClickActive = val === 'map';

  if (val !== 'map' && val !== 'address') clearPlanLocation();

  if (val === 'map') {
    clearPlanLocation();
    const mapTitle = document.querySelector('.map-title');
    if (mapTitle) mapTitle.textContent = t('map.pickLocation');
    ensurePlanMapClick();
    openMap();
  }
}

// Address autocomplete via Nominatim
const addrInput = document.getElementById('plan-addr-input');
const addrSugg  = document.getElementById('plan-addr-suggestions');
let addrDebounce = null;

function closeSuggestions() {
  addrSugg.style.display = 'none';
  addrSugg.innerHTML     = '';
}

function showSuggestions(results) {
  if (!results.length) { closeSuggestions(); return; }
  addrSugg.innerHTML = '';
  results.forEach(r => {
    const parts  = r.display_name.split(', ');
    const name   = parts.slice(0, 2).join(', ');
    const detail = parts.slice(2, 4).join(', ');
    const item   = document.createElement('div');
    item.className = 'addr-suggestion';
    item.innerHTML = `
      <div class="addr-suggestion-name">${escHtml(name)}</div>
      ${detail ? `<div class="addr-suggestion-detail">${escHtml(detail)}</div>` : ''}
    `;
    item.addEventListener('mousedown', e => {
      e.preventDefault();
      addrInput.value = name;
      setPlanLocation(parseFloat(r.lat), parseFloat(r.lon), name);
      closeSuggestions();
    });
    addrSugg.appendChild(item);
  });
  addrSugg.style.display = 'block';
}

addrInput.addEventListener('input', () => {
  clearTimeout(addrDebounce);
  const val = addrInput.value.trim();
  if (val.length < 3) { closeSuggestions(); return; }
  addrDebounce = setTimeout(async () => {
    try {
      const url = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(val)}&format=json&limit=5`;
      const res = await fetch(url, { headers: { 'Accept-Language': getLang() } });
      showSuggestions(await res.json());
    } catch { closeSuggestions(); }
  }, 300);
});

addrInput.addEventListener('keydown', e => { if (e.key === 'Escape') closeSuggestions(); });
document.addEventListener('click', e => { if (!e.target.closest('#plan-addr-wrap')) closeSuggestions(); });
