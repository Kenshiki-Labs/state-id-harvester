"""Conservative security-feature categories; observations never become runtime rules."""

from __future__ import annotations

import re
import unicodedata

FEATURE_PATTERNS: dict[str, str] = {
    "guilloche": r"\bguilloche\b",
    "tactile": r"\btactile\b|\btouchable indentations\b",
    "microprinting": r"\bmicroprint(?:ing)?\b|\bmicrotext\b",
    "ultraviolet": r"\bultraviolet\b|\buv\b|\b365\s*nm\b",
    "look_through": r"\blook[ -]?through\b|\bdlte\b",
    "ghost_portrait": r"\bghost\b",
    "polycarbonate": r"\bpolycarbonate\b",
    "laser_engraving": r"\blaser[ -]engrav(?:ed|ing)\b|\bengraved data\b",
    "optically_variable": r"\boptically variable\b|\bovd\b|\bovg\b",
    "multiple_laser_image": r"\bmli\b|\bmultiple laser image\b",
    "changeable_laser_image": r"\bcli\b|\bchangeable laser image\b",
    "lenticular": r"\blenticular\b",
    "retroreflective": r"\bretro[ -]?reflective\b",
    "tamper_void": r"\bvoid\b",
    "laser_perforation": r"\blaser perforations?\b",
    "hologram": r"\bhologram\b|\bholographic\b",
}


def features(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    normalized = re.sub(r"[\u2010-\u2015]", "-", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return sorted(
        name for name, pattern in FEATURE_PATTERNS.items() if re.search(pattern, normalized)
    )
