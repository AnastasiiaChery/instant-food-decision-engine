import { state } from './state.js';
import { setStatus } from './ui.js';
import { clearMarkers, showMapTrigger } from './map.js';
import { initAuth, openAuthModal } from './auth.js';
import { doAutopilot } from './autopilot.js';
import { doPlan } from './plan.js';

function switchMode(mode) {
  state.currentMode = mode;
  document.querySelectorAll('.mode-tab, .htab').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  document.querySelectorAll('.mode-panel').forEach(p => p.classList.remove('active'));
  document.getElementById('panel-' + mode).classList.add('active');
  document.getElementById('cardsGrid').innerHTML = '';
  state.cardMap.clear();
  clearMarkers();
  state.lastAutopilotPlace = null;
  state.recFallback        = null;
  showMapTrigger(0);
  setStatus('Ready');
}

document.querySelectorAll('.mode-tab, .htab').forEach(b => {
  b.addEventListener('click', () => switchMode(b.dataset.mode));
});

document.getElementById('autopilotBtn').addEventListener('click', doAutopilot);
document.getElementById('planBtn').addEventListener('click', doPlan);

initAuth();

document.getElementById('landingRegisterBtn')?.addEventListener('click', () => openAuthModal('register'));
document.getElementById('landingSignInBtn')?.addEventListener('click', () => openAuthModal('login'));
