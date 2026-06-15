"""UI string translation.

The base dictionary (static/i18n/en.json) is the single source of truth, written
by hand in English. Any other language is produced on demand by the LLM, then
cached both in memory and on disk (static/i18n/<lang>.json) so each language is
translated at most once. Pre-translating a language is as simple as committing a
<lang>.json file — it will be served directly without an LLM call.
"""

import asyncio
import json
import logging
import re
from pathlib import Path

from langchain_core.language_models import BaseChatModel

from app.infrastructure import cache

logger = logging.getLogger(__name__)

_I18N_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "i18n"
_BASE_LANG = "en"
# Redis key prefix for generated translations. Bump when en.json changes shape
# so stale cached translations (missing new keys) are not served indefinitely.
_REDIS_PREFIX = "i18n_v1"

# Accept ISO 639-1 codes, optionally with a region subtag (e.g. "pt-br").
_LANG_RE = re.compile(r"^[a-z]{2}(-[a-z]{2})?$")

# Languages the app officially offers (mirrors AVAILABLE_LANGS in static/js/i18n.js).
# The /api/v1/i18n/{lang} endpoint is unauthenticated and each uncached language
# triggers a real LLM translation call, so the accepted set is restricted to this
# whitelist — otherwise an attacker could loop arbitrary codes to burn LLM budget.
SUPPORTED_LANGS = frozenset({"en", "uk", "ru", "de", "es", "fr", "it", "pl", "pt"})

_cache: dict[str, dict[str, str]] = {}
_locks: dict[str, asyncio.Lock] = {}


def is_valid_lang(lang: str) -> bool:
    return bool(_LANG_RE.match(lang)) and lang in SUPPORTED_LANGS


def _load_base() -> dict[str, str]:
    if _BASE_LANG not in _cache:
        path = _I18N_DIR / f"{_BASE_LANG}.json"
        try:
            _cache[_BASE_LANG] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Base i18n dictionary {path} is missing or invalid: {exc}"
            ) from exc
    return _cache[_BASE_LANG]


def _load_from_disk(lang: str) -> dict[str, str] | None:
    path = _I18N_DIR / f"{lang}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("could not read cached translation %s", path)
        return None


def _write_to_disk(lang: str, data: dict[str, str]) -> None:
    """Best-effort persistence. A read-only filesystem (some PaaS) just means the
    in-memory cache is used until restart — not an error."""
    try:
        (_I18N_DIR / f"{lang}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2)
        )
    except OSError:
        logger.info("translation cache for %s not persisted (read-only fs)", lang)


_TRANSLATE_SYSTEM = (
    "You are a professional UI localizer for a food-discovery web app. "
    "You will receive a JSON object of English UI strings. Translate every VALUE "
    "into the language with ISO code '{lang}'. Rules:\n"
    "- Keep every KEY exactly as-is.\n"
    "- Do NOT translate or remove placeholder tokens in curly braces like {{count}}, "
    "{{radius}}, {{message}} — keep them verbatim.\n"
    "- Preserve any HTML tags (e.g. <br>, <em>) and currency symbols (€) exactly.\n"
    "- Keep leading/trailing arrows and symbols (→, ✓, ✕, 📍) where present.\n"
    "- Use natural, concise phrasing appropriate for buttons and labels.\n"
    "- Return ONLY a JSON object with the same keys — no commentary, no markdown."
)


# Translate in batches rather than one giant request. The base dictionary has
# grown past what a small model can return in a single response on a rate-limited
# tier (e.g. Groq free tier caps at 6000 tokens/minute): the reply was truncated
# mid-JSON, json.loads failed, and the whole language silently fell back to
# English — so the UI never switched. Each batch is small enough that input plus a
# bounded output stay well under the per-request budget, and one bad batch degrades
# only its own keys (via the merge below) instead of the entire dictionary.
_BATCH_SIZE = 40
# Bounded output per batch: large enough for ~40 translated values, small enough
# that input + this stays under tight per-minute token limits (avoids truncation
# AND "request too large" rejections).
_BATCH_MAX_TOKENS = 2000
# Small models occasionally emit a malformed value (e.g. a broken \uXXXX escape)
# that breaks json.loads for an otherwise-fine batch. Re-ask a few times before
# giving up on the batch — a fresh sample is usually valid.
_BATCH_PARSE_RETRIES = 3

# Some providers wrap the JSON in a ```json … ``` markdown fence despite being
# told not to. Strip it so json.loads sees raw JSON.
_FENCE_OPEN = re.compile(r"^```[a-zA-Z]*\n?")
_FENCE_CLOSE = re.compile(r"\n?```$")


def _strip_code_fence(content: str) -> str:
    s = content.strip()
    if s.startswith("```"):
        s = _FENCE_CLOSE.sub("", _FENCE_OPEN.sub("", s))
    return s.strip()


async def _invoke_batch(
    lang: str, batch: dict[str, str], ai_client: BaseChatModel
) -> dict[str, str]:
    """One LLM call for one batch. Raises JSONDecodeError on unparseable output;
    network/rate-limit errors propagate to the caller untouched."""
    system = _TRANSLATE_SYSTEM.format(lang=lang)
    payload = json.dumps(batch, ensure_ascii=False)
    # response_format forces strict JSON on OpenAI-compatible providers (Groq, OpenAI),
    # which a small model won't reliably produce on its own. Providers that reject the
    # kwarg (e.g. Gemini) fall back to a plain call + fence-stripped parse.
    try:
        llm = ai_client.bind(
            response_format={"type": "json_object"}, max_tokens=_BATCH_MAX_TOKENS
        )
        resp = await llm.ainvoke([("system", system), ("human", payload)])
    except Exception:
        logger.warning("response_format unsupported for this provider, retrying without it")
        llm = ai_client.bind(max_tokens=_BATCH_MAX_TOKENS)
        resp = await llm.ainvoke([("system", system), ("human", payload)])
    content = resp.content if isinstance(resp.content, str) else str(resp.content)
    translated = json.loads(_strip_code_fence(content))
    # Guard against the model dropping/adding keys: keep base value for any miss.
    return {k: translated.get(k, v) for k, v in batch.items()}


async def _translate_batch(
    lang: str, batch: dict[str, str], ai_client: BaseChatModel
) -> dict[str, str]:
    """Translate one batch, retrying on malformed JSON. If every attempt is
    unparseable, degrade *only this batch* to English rather than failing the whole
    language. (Infra/rate-limit errors are not caught here — they propagate so the
    caller fails the translation instead of caching an English-only result.)"""
    for attempt in range(_BATCH_PARSE_RETRIES):
        try:
            return await _invoke_batch(lang, batch, ai_client)
        except json.JSONDecodeError as exc:
            logger.warning(
                "unparseable translation batch for %s (attempt %d/%d): %s",
                lang, attempt + 1, _BATCH_PARSE_RETRIES, exc,
            )
    logger.error("giving up on a %s batch after %d tries, keeping English for it",
                 lang, _BATCH_PARSE_RETRIES)
    return dict(batch)


async def _translate_with_llm(
    lang: str, base: dict[str, str], ai_client: BaseChatModel
) -> dict[str, str]:
    items = list(base.items())
    batches = [
        dict(items[i : i + _BATCH_SIZE]) for i in range(0, len(items), _BATCH_SIZE)
    ]
    # Sequential, not concurrent: firing every batch at once just trips per-minute
    # rate limits. The provider client retries throttled batches transparently.
    result: dict[str, str] = {}
    for batch in batches:
        result.update(await _translate_batch(lang, batch, ai_client))
    return result


async def get_translations(lang: str, ai_client: BaseChatModel) -> dict[str, str]:
    """Return the UI dictionary for `lang`, translating + caching on first use.

    Falls back to the English base on any failure so the UI never breaks.
    """
    lang = lang.lower()
    base = _load_base()
    if lang == _BASE_LANG or not is_valid_lang(lang):
        return base

    if lang in _cache:
        return _cache[lang]

    lock = _locks.setdefault(lang, asyncio.Lock())
    async with lock:
        if lang in _cache:  # filled while we waited for the lock
            return _cache[lang]

        on_disk = _load_from_disk(lang)
        if on_disk is not None:
            # Merge over base so newly-added keys still resolve (to English) until
            # the cache file is regenerated.
            merged = {**base, **on_disk}
            _cache[lang] = merged
            return merged

        # Redis survives restarts on ephemeral/read-only filesystems (containers,
        # PaaS), so a language is translated by the LLM at most once across the
        # whole fleet rather than once per cold start.
        from_redis = await cache.get_json(f"{_REDIS_PREFIX}:{lang}")
        if isinstance(from_redis, dict):
            merged = {**base, **from_redis}
            _cache[lang] = merged
            return merged

        try:
            translated = await _translate_with_llm(lang, base, ai_client)
        except Exception:
            logger.exception("translation to %s failed, serving English", lang)
            return base

        _cache[lang] = translated
        _write_to_disk(lang, translated)
        await cache.set_json(f"{_REDIS_PREFIX}:{lang}", translated)
        return translated
