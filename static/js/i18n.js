// Lightweight i18n layer. Base dictionary is English (en.json); other languages
// are fetched from the backend, which LLM-translates and caches them on demand.

const STORAGE_KEY = 'instantfood_lang';

// Languages offered in the switcher. Any ISO code the backend accepts works at
// runtime; this list just controls what the dropdown shows. `native` is the
// label shown to the user in that language.
export const AVAILABLE_LANGS = [
  { code: 'en', native: 'English' },
  { code: 'uk', native: 'Українська' },
  { code: 'ru', native: 'Русский' },
  { code: 'de', native: 'Deutsch' },
  { code: 'es', native: 'Español' },
  { code: 'fr', native: 'Français' },
  { code: 'it', native: 'Italiano' },
  { code: 'pl', native: 'Polski' },
  { code: 'pt', native: 'Português' },
];

let dict = {};
let currentLang = 'en';

const dictCache = new Map(); // lang -> dict (avoid refetching on switch-back)

export function getLang() {
  return currentLang;
}

function detectLang() {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored) return stored;
  const nav = (navigator.language || 'en').slice(0, 2).toLowerCase();
  return AVAILABLE_LANGS.some(l => l.code === nav) ? nav : 'en';
}

// Turn a missing key into readable text, e.g. "taste.drinks" → "Drinks",
// "taste.cuisine.middle_eastern" → "Middle eastern". Used only as a last-resort
// fallback so the UI never shows a raw dotted key, even with a stale dictionary.
function humanize(key) {
  const last = String(key).split('.').pop().replace(/_/g, ' ');
  return last.charAt(0).toUpperCase() + last.slice(1);
}

// Translate a key, interpolating {placeholder} tokens from `vars`.
// Falls back to a humanized form of the key if the dictionary lacks it.
export function t(key, vars) {
  let s = dict[key];
  if (s == null) s = humanize(key);
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      s = s.replaceAll(`{${k}}`, String(v));
    }
  }
  return s;
}

async function fetchDict(lang) {
  if (dictCache.has(lang)) return dictCache.get(lang);
  const res = await fetch(`/api/v1/i18n/${encodeURIComponent(lang)}`);
  if (!res.ok) throw new Error(`i18n fetch failed: ${res.status}`);
  const data = await res.json();
  dictCache.set(lang, data);
  return data;
}

// Inline formatting tags permitted inside data-i18n-html strings. Everything
// else is unwrapped to its text content by the sanitizer below.
const ALLOWED_HTML_TAGS = new Set(['A', 'B', 'BR', 'EM', 'I', 'SPAN', 'STRONG']);

function isSafeHref(href) {
  const v = href.trim().toLowerCase();
  return v.startsWith('/') || v.startsWith('http://')
    || v.startsWith('https://') || v.startsWith('mailto:');
}

// Defense-in-depth: dictionaries for non-English languages are LLM-generated and
// fetched at runtime, so markup-bearing strings are sanitized before they reach
// innerHTML. Only the whitelisted inline tags survive; disallowed elements are
// unwrapped to their text, and every attribute is stripped except a safe href /
// target=_blank on anchors. A poisoned translation can therefore inject text but
// never scripts, event handlers or javascript: URLs.
function sanitizeHtml(html) {
  const tpl = document.createElement('template');
  tpl.innerHTML = html;
  // Static snapshot in document order: unwrapped children appear after their
  // parent here, so they're still visited and sanitized in turn.
  tpl.content.querySelectorAll('*').forEach(el => {
    if (!ALLOWED_HTML_TAGS.has(el.tagName)) {
      el.replaceWith(...el.childNodes);
      return;
    }
    [...el.attributes].forEach(attr => {
      const name = attr.name.toLowerCase();
      const keep = el.tagName === 'A'
        && ((name === 'href' && isSafeHref(attr.value))
          || (name === 'target' && attr.value === '_blank'));
      if (!keep) el.removeAttribute(attr.name);
    });
    if (el.tagName === 'A' && el.getAttribute('target') === '_blank') {
      el.setAttribute('rel', 'noopener noreferrer');
    }
  });
  return tpl.innerHTML;
}

// Apply the current dictionary to all annotated DOM nodes.
//   data-i18n            → textContent
//   data-i18n-html       → innerHTML (sanitized — see sanitizeHtml)
//   data-i18n-placeholder→ placeholder attribute
//   data-i18n-title      → title attribute
// Only overwrite when the dictionary actually has the key. Missing keys keep
// the element's hardcoded English text from the HTML — readable by design, so a
// stale or partial dictionary degrades to English instead of showing raw keys.
export function applyDOM(root = document) {
  root.querySelectorAll('[data-i18n]').forEach(el => {
    const v = dict[el.dataset.i18n];
    if (v != null) el.textContent = v;
  });
  root.querySelectorAll('[data-i18n-html]').forEach(el => {
    const v = dict[el.dataset.i18nHtml];
    if (v != null) el.innerHTML = sanitizeHtml(v);
  });
  root.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const v = dict[el.dataset.i18nPlaceholder];
    if (v != null) el.placeholder = v;
  });
  root.querySelectorAll('[data-i18n-title]').forEach(el => {
    const v = dict[el.dataset.i18nTitle];
    if (v != null) el.title = v;
  });
}

// Load a language and re-render. Notifies JS-driven strings via the
// `i18n:changed` event so modules that build text dynamically can refresh.
export async function setLang(lang) {
  try {
    dict = await fetchDict(lang);
  } catch (err) {
    console.error(err);
    if (lang !== 'en') return setLang('en');
    return;
  }
  currentLang = lang;
  localStorage.setItem(STORAGE_KEY, lang);
  document.documentElement.lang = lang;
  applyDOM();
  document.dispatchEvent(new CustomEvent('i18n:changed', { detail: { lang } }));
}

// Load the detected/stored language before first paint of dynamic content.
export async function initI18n() {
  await setLang(detectLang());
}
