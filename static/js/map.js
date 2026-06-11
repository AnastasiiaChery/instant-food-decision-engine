import { state } from './state.js';
import { t } from './i18n.js';

const mapModal = document.getElementById('mapModal');

export function initMap() {
  if (state.mapReady) return state.map;
  state.map = L.map('mapEl', { zoomControl: false }).setView([48.8566, 2.3522], 14);
  L.control.zoom({ position: 'topright' }).addTo(state.map);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 19,
  }).addTo(state.map);
  state.mapReady = true;
  return state.map;
}

export function openMap() {
  initMap();
  mapModal.classList.add('open');
  document.body.style.overflow = 'hidden';
  setTimeout(() => state.map.invalidateSize(), 60);
}

export function closeMap() {
  mapModal.classList.remove('open');
  document.body.style.overflow = '';
  if (state.planMapClickActive) {
    state.planMapClickActive = false;
    const mapTitle = document.querySelector('.map-title');
    if (mapTitle) mapTitle.textContent = t('map.nearbyPlaces');
    if (!state.planCustomLocation) {
      document.querySelectorAll('.plan-chip[data-group="loc"]').forEach(c => c.classList.remove('active'));
      document.querySelector('.plan-chip[data-group="loc"][data-val="gps"]')?.classList.add('active');
      document.getElementById('plan-map-hint').classList.remove('visible');
    }
  }
}

export function showMapTrigger(count) {
  document.getElementById('mapTrigger').classList.toggle('show', count > 0);
  const titleEl = document.querySelector('.map-title');
  if (titleEl) titleEl.textContent = count === 1 ? t('map.onePlaceNearby') : t('map.placesNearby', { count });
}

export function clearMarkers() {
  state.leafletMarkers.forEach(m => m.remove());
  state.leafletMarkers = [];
}

export function pinIcon(idx, isTop) {
  const s = isTop ? 32 : 26;
  return L.divIcon({
    className: '',
    html: `<div class="mpin${isTop ? ' top' : ''}">${idx + 1}</div>`,
    iconSize: [s, s],
    iconAnchor: [s / 2, s / 2],
  });
}

export function placeUserPin(lat, lng) {
  initMap();
  if (state.userCircle) state.userCircle.remove();
  state.userCircle = L.circleMarker([lat, lng], {
    radius: 7, fillColor: '#2455d4', color: '#fff', weight: 2.5, fillOpacity: 1,
  }).addTo(state.map).bindPopup(t('map.youAreHere'));
}

// Map modal event listeners
document.getElementById('mapTrigger').addEventListener('click', openMap);
document.getElementById('mapClose').addEventListener('click', closeMap);
mapModal.addEventListener('click', e => { if (e.target === mapModal) closeMap(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeMap(); });
