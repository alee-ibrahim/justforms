"""Text direction of form content (docs/DESIGN.md section 16).

A form has no language: each piece of text (each line of multi-line text) takes its direction
from its **dominant script** (more Thaana or more Latin words; a tie goes to the first strong
character), so Dhivehi (Thaana) text is right-to-left, English is left-to-right and a balanced
mixed label such as ``"Name / ނަން"`` follows whichever script comes first.
The frontend twin is ``frontend/src/schema/direction.ts``; both run
``spec/direction/vectors.json``.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal, TypedDict

Direction = Literal["ltr", "rtl"]

THAANA_START, THAANA_END = 0x0780, 0x07BF


def has_thaana(text: str | None) -> bool:
    """True when ``text`` holds any Thaana character."""
    return bool(text) and any(THAANA_START <= ord(ch) <= THAANA_END for ch in text or "")


def text_direction(text: str | None, default: Direction = "ltr") -> Direction:
    """Direction of ``text`` from its **dominant script**: the script with more words (runs of
    strong letters, combining marks included) wins, so a Dhivehi line that starts with a Latin
    acronym or a number ("PPY ގެ ބައިވެރިން ކޮބާ؟", "2026 ވަނަ އަހަރު.") still reads right to
    left. Words, not characters, are counted (Thaana vowels are separate marks, English words
    are longer). A tie goes to the first strong character (Unicode bidi rule P2); ``default``
    when the text has no letters."""
    first: Direction | None = None
    rtl = ltr = 0
    run: Direction | None = None
    for ch in text or "":
        cat = unicodedata.category(ch)
        if cat[0] == "L":
            d: Direction = "rtl" if unicodedata.bidirectional(ch) in ("R", "AL") else "ltr"
            if first is None:
                first = d
            if d != run:
                if d == "rtl":
                    rtl += 1
                else:
                    ltr += 1
                run = d
        elif cat[0] != "M":
            run = None
    if rtl != ltr:
        return "rtl" if rtl > ltr else "ltr"
    return first or default


def is_rtl(text: str | None) -> bool:
    return text_direction(text) == "rtl"


def text_lang(text: str | None) -> Literal["dv", "en"]:
    """``lang`` for a piece of form text: ``dv`` when it reads right to left in Thaana."""
    return "dv" if is_rtl(text) and has_thaana(text) else "en"


class TextLine(TypedDict):
    text: str
    dir: Direction
    lang: Literal["dv", "en"]


_LINE_BREAK = re.compile(r"\r\n|\r|\n")


def text_lines(text: str | None, default: Direction = "ltr") -> list[TextLine]:
    """Multi-line text (descriptions, paragraphs, long answers) line by line: each line
    break-separated paragraph takes its own direction from its dominant script, so an
    English paragraph followed by Dhivehi ones reads left to right, then right to left. A
    line with no strong character (blank, figures) takes the direction of the whole text."""
    base = text_direction(text, default)
    return [
        {"text": line, "dir": text_direction(line, base), "lang": text_lang(line)}
        for line in _LINE_BREAK.split(text or "")
    ]


def explicit_align(
    align: str | None, default: str | None
) -> Literal["left", "center", "right", "justify"] | None:
    """The explicit ``left``/``center``/``right``/``justify`` an element resolves to (its own,
    then the form default), or ``None`` for ``auto``: each paragraph then aligns to its own
    direction. ``justify`` is relative to each paragraph's direction too: wrapped lines are
    justified, the last line sits at the paragraph's start edge."""
    for value in (align, default):
        if value in ("left", "center", "right", "justify"):
            return value  # type: ignore[return-value]
        if value == "auto":
            break
    return None


def resolve_align(
    align: str | None, default: str | None, direction: Direction
) -> Literal["left", "center", "right"]:
    """Physical alignment of a text: an explicit ``left``/``center``/``right`` wins (element,
    then form default); ``auto`` (or nothing) follows the text's direction, and so does
    ``justify`` (a single line, or the last line of a justified paragraph, sits at its start)."""
    side = explicit_align(align, default)
    if side is not None and side != "justify":
        return side
    # auto, and justify for a single line: the text's start edge.
    return "right" if direction == "rtl" else "left"


def _script(ch: str) -> Literal["thaana", "latin", "neutral"]:
    if THAANA_START <= ord(ch) <= THAANA_END:
        return "thaana"
    return "latin" if unicodedata.category(ch)[0] == "L" else "neutral"


def isolate_runs(
    text: str, direction: Direction | None = None
) -> list[tuple[str, Direction | None]]:
    """``text`` split for display in a block whose direction is ``direction`` (default: the
    text's own): runs of the other script (Latin inside right-to-left text, Thaana inside
    left-to-right text) carry the direction to isolate them in (``<bdi>`` in HTML, LRI/RLI ...
    PDI in the PDF), so brackets and punctuation around them stay put ("(PPY)" inside Dhivehi).
    Neutrals between two letters of one script belong to that run. Twin of ``isolateRuns``
    (frontend/src/thaana/runs.ts); vectors ``isolate``."""
    base = direction or text_direction(text)
    minority = "latin" if base == "rtl" else "thaana"
    runs: list[list[str]] = []  # [script, text]
    pending = ""
    for ch in text:
        script = _script(ch)
        if script == "neutral":
            pending += ch
        elif runs and runs[-1][0] == script:
            runs[-1][1] += pending + ch
            pending = ""
        else:
            if pending:
                runs.append(["neutral", pending])
            pending = ""
            runs.append([script, ch])
    if pending:
        runs.append(["neutral", pending])
    out: list[tuple[str, Direction | None]] = []
    for kind, chunk in runs:
        if kind == minority:
            out.append((chunk, "rtl" if minority == "thaana" else "ltr"))
        elif out and out[-1][1] is None:
            out[-1] = (out[-1][0] + chunk, None)
        else:
            out.append((chunk, None))
    return out
