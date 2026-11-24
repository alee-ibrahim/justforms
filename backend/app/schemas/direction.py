"""Text direction of form content (docs/DESIGN.md section 16).

A form has no language: each piece of text takes its direction from its **first strong
character** (Unicode bidi rule P2), so Dhivehi (Thaana) text is right-to-left, English is
left-to-right and a mixed label such as ``"Name / ނަން"`` follows whichever script comes first.
The frontend twin is ``frontend/src/schema/direction.ts``; both run
``spec/direction/vectors.json``.
"""

from __future__ import annotations

import unicodedata
from typing import Literal

Direction = Literal["ltr", "rtl"]

THAANA_START, THAANA_END = 0x0780, 0x07BF


def has_thaana(text: str | None) -> bool:
    """True when ``text`` holds any Thaana character."""
    return bool(text) and any(THAANA_START <= ord(ch) <= THAANA_END for ch in text or "")


def text_direction(text: str | None, default: Direction = "ltr") -> Direction:
    """Direction of ``text`` from its first strong character; ``default`` when it has none."""
    for ch in text or "":
        kind = unicodedata.bidirectional(ch)
        if kind == "L":
            return "ltr"
        if kind in ("R", "AL"):
            return "rtl"
    return default


def is_rtl(text: str | None) -> bool:
    return text_direction(text) == "rtl"


def text_lang(text: str | None) -> Literal["dv", "en"]:
    """``lang`` for a piece of form text: ``dv`` when it reads right to left in Thaana."""
    return "dv" if is_rtl(text) and has_thaana(text) else "en"


def resolve_align(
    align: str | None, default: str | None, direction: Direction
) -> Literal["left", "center", "right"]:
    """Physical alignment of a text: an explicit ``left``/``center``/``right`` wins (element,
    then form default); ``auto`` (or nothing) follows the text's direction."""
    for value in (align, default):
        if value in ("left", "center", "right"):
            return value  # type: ignore[return-value]
        if value == "auto":
            break
    return "right" if direction == "rtl" else "left"
