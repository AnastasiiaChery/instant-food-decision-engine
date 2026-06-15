import { state } from './state.js';
import { escHtml, safeUrl, authHeaders, getToken } from './utils.js';
import { setStatus } from './ui.js';
import { recordNavigate } from './api.js';
import { track } from './analytics.js';
import { initMap, openMap, clearMarkers, pinIcon, showMapTrigger } from './map.js';
import { t } from './i18n.js';

const TOP_N = 5;

function placeKey(p) {
  return `${(p.name || '').trim().toLowerCase()}|${Number(p.lat).toFixed(5)}|${Number(p.lon).toFixed(5)}`;
}

export function addFeedbackWidget(container, place) {
  // Feedback posts to an authenticated endpoint, so don't show the widget to
  // guests — it would only fail silently on send.
  if (!getToken()) return;
  // Capture context at render time, not at click time
  const capturedMode = state.currentMode;
  const loc = state.lastSearchLocation;
  const originStr = loc ? `origin:${loc.lat.toFixed(5)},${loc.lng.toFixed(5)}` : null;
  let capturedQuery = null;
  if (capturedMode === 'plan') {
    const chip = g => document.querySelector(`.plan-chip[data-group="${g}"].active`)?.dataset.val;
    const when   = chip('when') || 'now';
    const group  = chip('group') || 'solo';
    const budget = chip('budget') || 'any';
    const radius = document.getElementById('planRadiusSlider')?.value || '1.5';
    const prefs  = document.getElementById('planQuery')?.value.trim();
    const parts  = [`when:${when}`, `group:${group}`, `budget:${budget}`, `radius:${radius}km`];
    if (prefs) parts.push(`prefs:${prefs}`);
    if (originStr) parts.push(originStr);
    capturedQuery = parts.join(' | ');
  } else if (originStr) {
    capturedQuery = originStr;
  }

  const wrap = document.createElement('div');
  wrap.className = 'feedback-wrap';
  wrap.innerHTML = `
    <button class="feedback-toggle">Not happy with this pick?</button>
    <div class="feedback-body">
      <textarea class="feedback-input" rows="2" maxlength="1000" placeholder="Tell us why…"></textarea>
      <button class="feedback-send">Send</button>
    </div>
  `;
  container.appendChild(wrap);

  wrap.querySelector('.feedback-toggle').addEventListener('click', () => {
    wrap.classList.toggle('open');
    if (wrap.classList.contains('open')) wrap.querySelector('.feedback-input').focus();
  });

  wrap.querySelector('.feedback-send').addEventListener('click', async () => {
    const comment = wrap.querySelector('.feedback-input').value.trim();
    if (!comment) return;
    const sendBtn = wrap.querySelector('.feedback-send');
    sendBtn.disabled = true;
    try {
      await fetch('/api/v1/feedback', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          place_name: place.name || '',
          query: capturedQuery,
          mode: capturedMode,
          comment,
        }),
      });
      wrap.innerHTML = '<span class="feedback-thanks">Thanks! We\'ll look into it.</span>';
    } catch (_) {
      sendBtn.disabled = false;
    }
  });

  wrap.addEventListener('click', e => e.stopPropagation());
}

export function addFavButton(container, place) {
  const btn = document.createElement('button');
  btn.className = 'fav-btn' + (getToken() ? ' visible' : '');
  btn.title = t('card.saveFav');
  btn.textContent = '♡';
  btn.addEventListener('click', e => {
    e.stopPropagation();
    if (!getToken()) return;
    btn.classList.add('active');
    btn.textContent = '♥';
    track('favorite_clicked', { type: place.amenity || 'restaurant' });
    fetch('/api/v1/history/navigate', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        place_name: place.name,
        place_type: place.amenity || 'restaurant',
        lat: place.lat,
        lng: place.lon,
        action_type: 'favorite',
      }),
    }).catch(() => {});
  });
  container.appendChild(btn);
  return btn;
}

function addShowMoreBtn(total) {
  const cardsGrid = document.getElementById('cardsGrid');
  const hidden = total - TOP_N;
  const btn = document.createElement('button');
  btn.className = 'show-more-btn';
  btn.textContent = t(hidden === 1 ? 'card.showMoreOne' : 'card.showMore', { count: hidden });
  btn.addEventListener('click', () => {
    cardsGrid.querySelectorAll('.card-hidden').forEach(c => c.classList.remove('card-hidden'));
    btn.remove();
  });
  cardsGrid.appendChild(btn);
}

export function renderPlaces(places) {
  const cardsGrid = document.getElementById('cardsGrid');
  cardsGrid.innerHTML = '';
  state.cardMap.clear();
  clearMarkers();
  initMap();

  places.forEach((p, i) => {
    const isTop   = i === 0;
    const card    = document.createElement('div');
    card.className = 'card' + (isTop ? ' top' : '');
    card.style.animationDelay = `${i * 0.05}s`;
    const cuisine = p.cuisine ? ` · ${escHtml(p.cuisine)}` : '';
    card.innerHTML = `
      <div class="card-head">
        <div class="rank-badge">${i + 1}</div>
        <div class="card-name">${escHtml(p.name || t('card.unnamed'))}</div>
        <div class="score-pill"></div>
      </div>
      <div class="card-meta">${Math.round(p.distance_m)}m · ${escHtml(p.amenity || t('card.food'))}${cuisine}</div>
      <div class="card-reason"><div class="skel"></div><div class="skel short"></div></div>
      <a class="card-nav" href="${escHtml(safeUrl(p.nav_url))}" target="_blank" rel="noopener noreferrer">${escHtml(t('card.navigate'))}</a>
    `;
    cardsGrid.appendChild(card);
    addFavButton(card, p);
    addFeedbackWidget(card, p);
    card.querySelector('.card-nav').addEventListener('click', () => recordNavigate(p));

    const marker = L.marker([p.lat, p.lon], { icon: pinIcon(i, isTop) })
      .addTo(state.map)
      .bindPopup(`<strong>${escHtml(p.name)}</strong><br>${Math.round(p.distance_m)}m`);
    marker.on('click', () => card.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
    card.addEventListener('click', e => {
      if (e.target.closest('.card-nav')) return;
      openMap();
      setTimeout(() => state.map.flyTo([p.lat, p.lon], 16, { animate: true, duration: 0.5 }), 80);
      setTimeout(() => marker.openPopup(), 700);
    });
    state.leafletMarkers.push(marker);
    state.cardMap.set(placeKey(p), { card, markerIdx: i });
  });

  showMapTrigger(places.length);
}

export function applyRanking(ranked) {
  ranked = [...ranked].sort((a, b) => b.match_score - a.match_score || a.distance_m - b.distance_m);
  const keepKeys  = new Set(ranked.map(placeKey));
  const cardsGrid = document.getElementById('cardsGrid');
  [...state.cardMap.entries()].forEach(([key, { card, markerIdx }]) => {
    if (!keepKeys.has(key)) { card.remove(); state.leafletMarkers[markerIdx]?.remove(); }
  });
  ranked.forEach((p, i) => {
    const entry = state.cardMap.get(placeKey(p));
    if (!entry) return;
    const { card, markerIdx } = entry;
    const isTop = i === 0;
    card.className = 'card' + (isTop ? ' top' : '') + (i >= TOP_N ? ' card-hidden' : '');
    const rankEl = card.querySelector('.rank-badge');
    if (rankEl) rankEl.textContent = i + 1;
    const scoreEl = card.querySelector('.score-pill');
    if (scoreEl && p.match_score != null) {
      scoreEl.textContent = Math.round(p.match_score * 100) + '%';
      scoreEl.classList.add('show');
    }
    const reasonEl = card.querySelector('.card-reason');
    if (reasonEl) reasonEl.textContent = p.reason || '';
    cardsGrid.appendChild(card);
    state.leafletMarkers[markerIdx]?.setIcon(pinIcon(i, isTop));
  });
  if (ranked.length > TOP_N) addShowMoreBtn(ranked.length);
}

export function renderRecommendation(data, animate = true, onRetry = null) {
  const { place, reason, signals = [], fallback_place, fallback_signals = [] } = data;
  state.recFallback = fallback_place
    ? { place: fallback_place, reason: fallback_place.reason, signals: fallback_signals, fallback_place: null, fallback_signals: [] }
    : null;

  const cuisine   = place.cuisine ? ` · ${escHtml(place.cuisine)}` : '';
  const cardsGrid = document.getElementById('cardsGrid');
  cardsGrid.innerHTML = '';
  state.cardMap.clear();
  clearMarkers();
  initMap();

  const signalHtml = signals.length
    ? `<div class="rec-signals">${signals.map(s => `<span class="rec-signal">${escHtml(s)}</span>`).join('')}</div>`
    : '';

  const card = document.createElement('div');
  card.className = 'rec-card';
  if (animate) card.style.animation = 'fadeUp 0.3s ease both';
  card.innerHTML = `
    <div class="rec-badge">${escHtml(t('rec.aiPick'))}</div>
    <div class="rec-name">${escHtml(place.name || t('card.unnamed'))}</div>
    <div class="rec-meta">${escHtml(place.amenity || t('card.food'))}${cuisine}</div>
    ${signalHtml}
    <div class="rec-why-label">${escHtml(t('rec.whyThis'))}</div>
    <div class="rec-reason"></div>
    <div class="rec-actions">
      <a class="rec-nav" href="${escHtml(safeUrl(place.nav_url))}" target="_blank" rel="noopener noreferrer">${escHtml(t('card.navigate'))}</a>
      <button class="rec-another">${escHtml(state.recFallback ? t('rec.showAnother') : t('rec.tryAgain'))}</button>
    </div>
  `;
  card.querySelector('.rec-reason').textContent = reason || '';
  cardsGrid.appendChild(card);
  addFavButton(card, place);
  addFeedbackWidget(card, place);
  card.querySelector('.rec-nav').addEventListener('click', () => recordNavigate(place));
  card.querySelector('.rec-another').addEventListener('click', () => {
    if (state.recFallback) {
      if (place.name && !state.autopilotSeen.includes(place.name)) state.autopilotSeen.push(place.name);
      const fb = state.recFallback;
      state.recFallback = null;
      card.classList.add('swapping');
      setTimeout(() => {
        renderRecommendation(fb, false, onRetry);
        setStatus(t('status.anotherOption'), 'done');
      }, 180);
    } else if (onRetry) {
      onRetry();
    }
  });

  const marker = L.marker([place.lat, place.lon], { icon: pinIcon(0, true) })
    .addTo(state.map)
    .bindPopup(`<strong>${escHtml(place.name)}</strong><br>${Math.round(place.distance_m)}m`);
  state.leafletMarkers.push(marker);
  showMapTrigger(1);
}

export function renderPlanRecommendations(data) {
  const recs      = data.recommendations || [];
  const cardsGrid = document.getElementById('cardsGrid');
  cardsGrid.innerHTML = '';
  state.cardMap.clear();
  clearMarkers();
  initMap();

  if (data.notice) {
    const banner = document.createElement('div');
    banner.className = 'plan-notice';
    banner.textContent = data.notice;
    cardsGrid.appendChild(banner);
  }

  recs.forEach((rec, i) => {
    const { place, reason, scenario } = rec;
    const cuisine = place.cuisine ? ` · ${escHtml(place.cuisine)}` : '';
    const card    = document.createElement('div');
    card.className = 'card' + (i === 0 ? ' top' : '') + (i >= TOP_N ? ' card-hidden' : '');
    card.style.animationDelay = `${i * 0.07}s`;
    card.innerHTML = `
      <div class="card-head">
        <div class="rank-badge">${i + 1}</div>
        <div class="card-name">${escHtml(place.name || t('card.unnamed'))}</div>
        ${scenario ? `<div class="score-pill show">${escHtml(scenario)}</div>` : ''}
      </div>
      <div class="card-meta">${Math.round(place.distance_m)}m · ${escHtml(place.amenity || t('card.food'))}${cuisine}</div>
      <div class="card-reason"></div>
      <a class="card-nav" href="${escHtml(safeUrl(place.nav_url))}" target="_blank" rel="noopener noreferrer">${escHtml(t('card.navigate'))}</a>
    `;
    card.querySelector('.card-reason').textContent = reason || '';
    cardsGrid.appendChild(card);
    addFavButton(card, place);
    addFeedbackWidget(card, place);
    card.querySelector('.card-nav').addEventListener('click', () => recordNavigate(place));
    card.addEventListener('click', e => {
      if (e.target.closest('.card-nav')) return;
      openMap();
      setTimeout(() => state.map.flyTo([place.lat, place.lon], 16), 80);
    });
    if (place.lat && place.lon) {
      const marker = L.marker([place.lat, place.lon], { icon: pinIcon(i, i === 0) })
        .addTo(state.map)
        .bindPopup(`<strong>${escHtml(place.name)}</strong><br>${Math.round(place.distance_m)}m`);
      state.leafletMarkers.push(marker);
    }
  });

  if (recs.length > TOP_N) addShowMoreBtn(recs.length);
  showMapTrigger(recs.length);
}
