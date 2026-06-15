"""Pre-generate i18n dictionaries for every offered language and write them to
static/i18n/<lang>.json.

Run offline once (and again whenever en.json gains keys). Committing the produced
files lets the server serve translations straight from disk — no runtime LLM call,
no per-minute rate limits, instant language switching. See app/services/translator.py.

    python scripts/pretranslate_i18n.py            # all missing languages
    python scripts/pretranslate_i18n.py ru uk      # only these
    python scripts/pretranslate_i18n.py --force ru # re-translate even if file exists
    python scripts/pretranslate_i18n.py --check    # validate existing files, no LLM

Each generated (or, with --check, existing) file is validated against en.json:
small models occasionally invent fake URLs, drop a placeholder/HTML tag, or emit
text in the wrong language (Chinese glyphs, Spanish words in a Ukrainian file).
These slip past json.loads, so we check them explicitly. The process exits non-zero
if any HARD issue is found, so a bad generation fails loudly instead of shipping.
"""

import asyncio
import json
import logging
import re
import sys

from app.core.deps import build_ai_clients
from app.services import translator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("pretranslate")

# Languages written in Cyrillic — used to flag stray Latin-script words, which in
# these files almost always mean an untranslated or wrong-language value.
_CYRILLIC_LANGS = {"ru", "uk", "be", "bg", "sr", "mk"}

_HREF = re.compile(r'href="([^"]+)"')
_PLACEHOLDER = re.compile(r"\{[a-zA-Z_]+\}")
_TAG = re.compile(r"<\s*([a-zA-Z]+)")
# CJK ideographs, Hiragana/Katakana, Hangul — never valid in our target languages.
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
# Tokens that are legitimately Latin even inside a Cyrillic translation.
_LATIN_ALLOWED = re.compile(
    r"(AI|NomPilot|Google|OpenStreetMap|GPS|OK|km|€"
    r"|<[^>]+>|&[a-zA-Z]+;|\{[a-zA-Z_]+\}|https?://\S+|/[a-z]+)",
    re.I,
)


def validate(lang: str, base: dict[str, str], data: dict[str, str]) -> list[str]:
    """Return a list of "HARD: ..." / "WARN: ..." issue strings for one language."""
    issues: list[str] = []

    missing = [k for k in base if k not in data]
    if missing:
        issues.append(f"HARD: {len(missing)} missing keys: {missing[:5]}")

    for k, en in base.items():
        v = str(data.get(k, ""))

        if _HREF.findall(en) != _HREF.findall(v):
            issues.append(
                f"HARD: {k}: href changed {_HREF.findall(en)} -> {_HREF.findall(v)}"
            )

        if set(_PLACEHOLDER.findall(en)) != set(_PLACEHOLDER.findall(v)):
            issues.append(f"HARD: {k}: placeholder mismatch ({en!r} -> {v!r})")

        if sorted(t.lower() for t in _TAG.findall(en)) != sorted(
            t.lower() for t in _TAG.findall(v)
        ):
            issues.append(f"HARD: {k}: HTML tag mismatch ({en!r} -> {v!r})")

        if _CJK.search(v):
            issues.append(f"HARD: {k}: CJK characters in {lang} ({v!r})")

        if lang in _CYRILLIC_LANGS and re.search(r"[A-Za-z]", _LATIN_ALLOWED.sub("", v)):
            issues.append(f"WARN: {k}: stray Latin text in {lang} ({v!r})")

    return issues


def report(lang: str, issues: list[str]) -> int:
    """Log issues; return the number of HARD ones."""
    hard = [i for i in issues if i.startswith("HARD")]
    for i in issues:
        (logger.error if i.startswith("HARD") else logger.warning)("[%s] %s", lang, i)
    if not issues:
        logger.info("[%s] validation OK", lang)
    return len(hard)


async def main(argv: list[str]) -> int:
    force = "--force" in argv
    check_only = "--check" in argv
    wanted = [a for a in argv if not a.startswith("--")]
    langs = wanted or sorted(translator.SUPPORTED_LANGS - {"en"})

    base = translator._load_base()
    out_dir = translator._I18N_DIR

    if check_only:
        hard = 0
        for lang in langs:
            path = out_dir / f"{lang}.json"
            if not path.exists():
                logger.error("[%s] missing file %s", lang, path)
                hard += 1
                continue
            hard += report(lang, validate(lang, base, json.loads(path.read_text())))
        logger.info("check complete (%d hard issues)", hard)
        return 1 if hard else 0

    client = build_ai_clients()["fast"]
    failures, hard_total = [], 0
    for lang in langs:
        path = out_dir / f"{lang}.json"
        if path.exists() and not force:
            logger.info("skip %s (already exists; use --force to overwrite)", lang)
            continue
        logger.info("translating %s (%d keys)...", lang, len(base))
        try:
            data = await translator._translate_with_llm(lang, base, client)
        except Exception:
            logger.exception("FAILED %s", lang)
            failures.append(lang)
            continue
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        changed = sum(1 for k in base if data.get(k) != base[k])
        logger.info("wrote %s (%d/%d keys translated)", path, changed, len(base))
        hard_total += report(lang, validate(lang, base, data))

    if failures:
        logger.error("done with failures: %s", ", ".join(failures))
        return 1
    if hard_total:
        logger.error("done, but %d hard validation issues need a manual fix", hard_total)
        return 1
    logger.info("all done")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
