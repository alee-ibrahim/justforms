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


def _script_runs(text: str) -> list[list[str]]:
    """``[script, text]`` runs; neutrals between two letters of one script join that run."""
    runs: list[list[str]] = []
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
    return runs


_OPENERS = "([{"
_CLOSERS = ")]}"


def _unclosed(text: str) -> list[str]:
    """Closers still owed by the openers in ``text``, innermost last."""
    stack: list[str] = []
    for ch in text:
        o = _OPENERS.find(ch)
        if o >= 0:
            stack.append(_CLOSERS[o])
        elif stack and stack[-1] == ch:
            stack.pop()
    return stack


def _pair_brackets(runs: list[list[str]], i: int) -> None:
    """A bracket pair belongs to the run it encloses: closers right after a run that it opened
    move into it, and an opener just before it whose closer follows right after wraps it."""
    run = runs[i]
    nxt = runs[i + 1] if i + 1 < len(runs) and runs[i + 1][0] == "neutral" else None
    prev = runs[i - 1] if i > 0 and runs[i - 1][0] == "neutral" else None
    if nxt is not None:
        stack = _unclosed(run[1])
        k = 0
        while stack and k < len(nxt[1]) and nxt[1][k] == stack[-1]:
            stack.pop()
            k += 1
        run[1] += nxt[1][:k]
        nxt[1] = nxt[1][k:]
    while prev is not None and nxt is not None and prev[1] and nxt[1]:
        o = _OPENERS.find(prev[1][-1])
        if o < 0 or nxt[1][0] != _CLOSERS[o]:
            break
        run[1] = prev[1][-1] + run[1] + nxt[1][0]
        prev[1] = prev[1][:-1]
        nxt[1] = nxt[1][1:]


def isolate_runs(
    text: str, direction: Direction | None = None
) -> list[tuple[str, Direction | None]]:
    """``text`` split for display in a block whose direction is ``direction`` (default: the
    text's own): runs of the other script (Latin inside right-to-left text, Thaana inside
    left-to-right text) carry the direction to isolate them in (``<bdi>`` in HTML, LRI/RLI ...
    PDI in the PDF), so brackets and punctuation around them stay put ("(PPY)" inside Dhivehi).
    Neutrals between two letters of one script belong to that run; a bracket pair belongs to
    the run it encloses. Twin of ``isolateRuns`` (frontend/src/thaana/runs.ts); vectors
    ``isolate``."""
    base = direction or text_direction(text)
    minority = "latin" if base == "rtl" else "thaana"
    runs = _script_runs(text)
    for i, (kind, _chunk) in enumerate(runs):
        if kind == minority:
            _pair_brackets(runs, i)
    out: list[tuple[str, Direction | None]] = []
    for kind, chunk in runs:
        if not chunk:
            continue
        if kind == minority:
            out.append((chunk, "rtl" if minority == "thaana" else "ltr"))
        elif out and out[-1][1] is None:
            out[-1] = (out[-1][0] + chunk, None)
        else:
            out.append((chunk, None))
    return out


class BilingualParts(TypedDict):
    ltr: str
    rtl: str
    first: Direction


# Always a divider between two parts, however short they are.
_STRONG = re.compile(r"[/|]")
# Where the gap between the parts is cut: at a divider ("/", "|", a spaced dash or bullet), else
# at its last spaces; the divider and spaces are dropped.
_CUT = re.compile(r"\s*[/|]\s*|\s+[\u2010-\u2015\u2022\u00b7-]+\s+")
_LAST_SPACES = re.compile(r"\s+(?=\S*$)")
# Without spaces: the closers and punctuation that end the first part (Dhivehi "؟", "،", "؛").
_ENDING = re.compile(r"[)\]}:;,.!?\u061f\u060c\u061b\u2026]*")


def _words(text: str) -> int:
    count = 0
    in_word = False
    for ch in text:
        letter = unicodedata.category(ch)[0] in ("L", "M")
        if letter and not in_word:
            count += 1
        in_word = letter
    return count


def bilingual_parts(text: str | None) -> BilingualParts | None:
    """Splits a one-line text that is **one English block and one Dhivehi block** (either
    order, "Full name: ފުރިހަމަ ނަން") into its two parts, each with the punctuation that ends
    it and the brackets that enclose it, the divider between them dropped; ``None`` otherwise:
    multi-line text, one script, more than two script blocks (an acronym inside a Dhivehi
    sentence), two blocks with only spaces between them ("PPY ގެ ބައިވެރިން"), and, unless "/"
    or "|" divides them, a lone capitalised acronym or a short run tacked onto a long sentence
    (the shorter part needs two words or half the longer's). Rendered as one row, English at
    the left and Dhivehi at the right. Twin of ``bilingualParts``
    (frontend/src/thaana/runs.ts); vectors ``bilingual``."""
    if not text or "\n" in text or "\r" in text:
        return None
    runs = _script_runs(text)
    letters = [i for i, r in enumerate(runs) if r[0] != "neutral"]
    if len(letters) != 2 or runs[letters[0]][0] == runs[letters[1]][0]:
        return None
    a, b = letters
    gap = runs[a + 1][1] if b > a + 1 else ""
    # Something other than spaces (and figures) must mark the break between the two parts.
    if not re.search(r"[^\s\d]", gap):
        return None
    latin_first = runs[a][0] == "latin"
    latin, thaana = (runs[a][1], runs[b][1]) if latin_first else (runs[b][1], runs[a][1])
    latin_words = _words(latin)
    short = min(latin_words, _words(thaana))
    long = max(latin_words, _words(thaana))
    acronym = latin_words == 1 and not any(unicodedata.category(c) == "Ll" for c in latin)
    if not _STRONG.search(gap) and (acronym or (short < 2 and short * 2 < long)):
        return None
    # The first part keeps what ends it (":", "?", its closing brackets), the second what opens
    # it.
    cut = _CUT.search(gap) or _LAST_SPACES.search(gap)
    if cut:
        start, end = cut.span()
    else:
        start = end = _ENDING.match(gap).end()  # type: ignore[union-attr]
    first = ("".join(r[1] for r in runs[: a + 1]) + gap[:start]).strip()
    second = (gap[end:] + "".join(r[1] for r in runs[b:])).strip()
    if latin_first:
        return {"ltr": first, "rtl": second, "first": "ltr"}
    return {"ltr": second, "rtl": first, "first": "rtl"}
