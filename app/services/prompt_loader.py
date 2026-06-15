"""Loads the LLM system prompts shipped under app/services/prompts/.

Prompts are read at import time. A missing or unreadable file is fatal (the LLM
steps can't work without it), but we raise a clear configuration error instead of
letting a bare OSError surface as an opaque traceback at startup.
"""

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / name
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"Required prompt file {path} is missing or unreadable: {exc}"
        ) from exc
