export function setStatus(text, state = '') {
  document.getElementById('statusText').textContent = text;
  const dot = document.getElementById('dot');
  dot.className = 'dot' + (state ? ' ' + state : '');
}

export function useProfile() {
  return document.getElementById('useProfileToggle')?.checked ?? true;
}
