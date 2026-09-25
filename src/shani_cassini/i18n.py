"""i18n translation module for shani-cassini."""

import os
import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_PO_DIR = Path(__file__).resolve().parent.parent.parent / "po"
_CURRENT_LOCALE = "en"
_TRANSLATIONS: dict[str, str] = {}


def load_po(locale: str = "en") -> dict[str, str]:
    """Load a .po file and return msgid -> msgstr mapping."""
    po_path = _PO_DIR / f"{locale}.po"
    if not po_path.exists():
        logger.warning("Translation file not found: %s", po_path)
        return {}

    translations = {}
    current_msgid = None
    in_msgstr = False

    with open(po_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith('msgid "'):
                current_msgid = line[7:line.rfind('"')]
                in_msgstr = False
            elif line.startswith('msgstr "'):
                in_msgstr = True
                msgstr = line[8:line.rfind('"')]
                if current_msgid and msgstr:
                    translations[current_msgid] = msgstr
            elif in_msgstr and line.startswith('"') and line.endswith('"'):
                if current_msgid:
                    translations[current_msgid] += line[1:-1]

    return translations


def set_locale(locale: str) -> None:
    """Set the current locale and load translations."""
    global _CURRENT_LOCALE, _TRANSLATIONS
    _CURRENT_LOCALE = locale
    _TRANSLATIONS = load_po(locale)
    logger.info("Locale set to: %s", locale)


def translate(text: str) -> str:
    """Translate a string to the current locale."""
    return _TRANSLATIONS.get(text, text)


def get_locale() -> str:
    """Get the current locale."""
    return _CURRENT_LOCALE


_LOCALE_DIR = _PO_DIR  # sibling `po/` dir holding <lang>.po catalogs


def detect_locale() -> str:
    """Pick the best available translation for the running desktop session.

    Uses GLib (the GTK runtime's locale database) to read the ordered list of
    preferred languages, then returns the first one for which a `<lang>.po`
    catalog exists in the sibling `po/` directory. Falls back to LANGUAGE/LANG
    env vars, then to "en". Never raises when GLib is unavailable.
    """
    candidates: list[str] = []
    try:
        from gi.repository import GLib  # type: ignore

        names = GLib.get_language_names()  # ordered by preference
        for n in names:
            lang = str(n)
            candidates.append(lang)
            # glibc-style "ll_CC" → "ll" coarse fallback
            if "_" in lang:
                candidates.append(lang.split("_", 1)[0])
    except Exception:  # noqa: BLE001 — GLib optional
        pass

    for env_name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(env_name, "")
        if val:
            for part in val.split(":"):
                part = part.strip()
                if part:
                    candidates.append(part)
                    if "_" in part:
                        candidates.append(part.split("_", 1)[0])

    for lang in candidates:
        if (_LOCALE_DIR / f"{lang}.po").is_file():
            return lang
    return "en"


# Initialize with the detected locale (or "en" as a safe default).
set_locale(detect_locale())
