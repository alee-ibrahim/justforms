"""Thaana -> Latin (official 1977 rules) and addresses from titles, run against the vectors
shared with the frontend twin (``spec/slugs``, also run by vitest)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.services import slugs
from app.text.thaana_latin import has_thaana, romanise, romanise_word

SPEC = Path(__file__).resolve().parents[2] / "spec" / "slugs"
LATIN: dict[str, Any] = json.loads((SPEC / "thaana-latin.json").read_text(encoding="utf-8"))
SLUGS: dict[str, Any] = json.loads((SPEC / "slugs.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", LATIN["words"], ids=lambda c: c["latin"])
def test_booklet_examples(case: dict[str, str]) -> None:
    assert romanise_word(case["thaana"]) == case["latin"]


@pytest.mark.parametrize("case", LATIN["texts"], ids=lambda c: c["latin"][:30])
def test_texts(case: dict[str, str]) -> None:
    assert romanise(case["thaana"]) == case["latin"]


@pytest.mark.parametrize("case", SLUGS["cases"], ids=lambda c: c["slug"])
def test_title_slugs(case: dict[str, str]) -> None:
    slug = slugs.slugify(case["title"])
    assert slug == case["slug"]
    assert slugs.SLUG.match(slug)
    assert len(slug) <= slugs.TITLE_LENGTH


def test_vectors_cover_the_rules() -> None:
    """Every section the module automates has a booklet example."""
    latin = {c["latin"] for c in LATIN["words"]}
    assert {"meeheh", "fen", "foiy", "gas", "bappa", "bayyeh", "mamma", "kan'di"} <= latin
    assert len(LATIN["words"]) == 68


def test_has_thaana_and_pass_through() -> None:
    assert has_thaana("Survey ފޯމު") and not has_thaana("Survey 2026")
    assert romanise("Survey 2026") == "Survey 2026"
    assert romanise("ފޯމު - Form") == "Foamu - Form"


def test_generic_slugs() -> None:
    assert slugs.is_generic("form") and slugs.is_generic("form-12")
    assert not slugs.is_generic("forms") and not slugs.is_generic("form-x")
    assert not slugs.is_generic("foamu")
