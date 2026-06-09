import { getToken } from './utils.js';

export function getLocation() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) { reject(new Error('Geolocation not supported.')); return; }
    navigator.geolocation.getCurrentPosition(
      p => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
      e => {
        if (e.code === 1) reject(new Error('Location permission denied.'));
        else if (e.code === 2) reject(new Error('Location unavailable.'));
        else reject(new Error('Location timed out. Please use Plan mode and enter your address manually.'));
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

export function recordNavigate(place, notes) {
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
      place_notes: notes || null,
    }),
  }).catch(() => {});
}
