"""Thaana -> Latin by the official romanisation rules of 23 May 1977.

Ported from ``dhivehi_rules/thaana_latin.py`` in https://github.com/alee-ibrahim/dhivehi-rules
(MIT License, Copyright (c) 2026 Alee Ibrahim). The TypeScript twin is
``frontend/src/thaana/latin.ts``; both run the vectors in ``spec/slugs/`` (the rule booklet's
own examples plus slug cases), so change them together.

Used for form addresses: a Dhivehi title gets a readable slug instead of a generic one.

    §1 consonants    ހ h  ށ sh  ނ n  ރ r  ބ b  ޅ lh  ކ k  ވ v  މ m  ފ f  ދ dh  ތ th
                     ލ l  ގ g  ޏ gn  ސ s  ޑ d  ޒ z  ޓ t  ޔ y  ޕ p  ޖ j  ޗ ch
    §2 Arabic        ޞ s'  ޟ l'  ޠ t'  ޡ z'  ޥ w  ޘ th'  ޙ h'  ޚ kh  ޛ dh'  ޣ gh  ޤ q
                     ޝ as the Dhivehi sound (sh); ޢ = the vowel with an apostrophe (a'mal)
    §3 vowels        ަ a  ާ aa  ި i  ީ ee  ު u  ޫ oo  ެ e  ޭ ey  ޮ o  ޯ oa ; އ + vowel = the vowel
    §4 sukun         final އް -> h (meeheh), ން -> n (fen), ށް -> iy (foiy), ސް -> s (gas);
                     before a consonant: that consonant, doubled after އް (bappa, bayyeh),
                     ން before މ -> m (mamma)
    §5               a bare ނ before a consonant -> n' (kan'di, an'bu)
    §6               a sentence begins with a capital

Capitals for proper nouns and English words kept in English spelling (§8) are word-level
judgements this module does not make.
"""

from __future__ import annotations

import re

CONS: dict[str, str] = {
    "ހ": "h", "ށ": "sh", "ނ": "n", "ރ": "r", "ބ": "b", "ޅ": "lh", "ކ": "k", "އ": "",
    "ވ": "v", "މ": "m", "ފ": "f", "ދ": "dh", "ތ": "th", "ލ": "l", "ގ": "g", "ޏ": "gn",
    "ސ": "s", "ޑ": "d", "ޒ": "z", "ޓ": "t", "ޔ": "y", "ޕ": "p", "ޖ": "j", "ޗ": "ch",
    "ޞ": "s'", "ޟ": "l'", "ޠ": "t'", "ޡ": "z'", "ޥ": "w", "ޘ": "th'", "ޙ": "h'",
    "ޚ": "kh", "ޛ": "dh'", "ޝ": "sh", "ޣ": "gh", "ޤ": "q", "ޜ": "zh", "ޢ": "",
}  # fmt: skip
VOWEL: dict[str, str] = {
    "ަ": "a", "ާ": "aa", "ި": "i", "ީ": "ee", "ު": "u", "ޫ": "oo",
    "ެ": "e", "ޭ": "ey", "ޮ": "o", "ޯ": "oa",
}  # fmt: skip
SUKUN = "ް"
_LONG = frozenset({"aa", "ee", "oo", "ey", "oa"})
PUNCT = {"،": ",", "؟": "?", "؛": ";"}
THAANA = re.compile("[ހ-޿]")


def has_thaana(text: str) -> bool:
    return THAANA.search(text) is not None


def _word(w: str) -> str:
    out: list[str] = []
    i, n = 0, len(w)
    while i < n:
        c = w[i]
        nxt = w[i + 1] if i + 1 < n else ""
        if c in VOWEL or c == SUKUN:  # stray mark: nothing to attach it to
            i += 1
            continue
        if c not in CONS:
            out.append(PUNCT.get(c, c))
            i += 1
            continue
        if nxt in VOWEL:
            v = VOWEL[nxt]
            if c == "ޢ":  # §2: a'mal, i'shq, Maso'odh, a'ailaa
                out.append(v[0] + "'" + v[1:] if v in _LONG else v + "'")
            else:
                out.append(CONS[c] + v)
            i += 2
            continue
        if nxt == SUKUN:
            after = w[i + 2] if i + 2 < n else ""
            final = after == "" or after not in CONS
            if c == "އ":
                if final:
                    out.append("h")  # §4: meeheh
                elif CONS[after]:
                    out.append(CONS[after])  # §4: bappa, bayyeh
            elif c == "ށ" and final:
                out.append("iy")  # §4: foiy, baiy
            elif c == "ނ" and after == "މ":
                out.append("m")  # §4: mamma
            else:
                out.append(CONS[c])  # fen, gas, ramzu, milku
            i += 2
            continue
        if c == "ނ" and nxt in CONS:  # §5: prenasalised stop
            out.append("n'")
            i += 1
            continue
        out.append(CONS[c])  # bare letter: an abbreviation
        i += 1
    return "".join(out)


def romanise_word(word: str) -> str:
    """One word, without §6's capital (the booklet's examples are given this way)."""
    return _word(word)


def romanise(text: str) -> str:
    """Official 1977 romanisation of a Thaana text; sentences start with a capital. Latin
    letters, digits and other characters pass through unchanged."""
    parts = re.split(r"(\s+)", text)
    out = "".join(_word(p) if p.strip() else p for p in parts)
    # §6: a capital at the start of each sentence.
    return re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), out)
