"""Per-text direction and alignment (app/schemas/direction.py), shared with the frontend twin
through spec/direction/vectors.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.schemas.direction import (
    bilingual_parts,
    explicit_align,
    has_thaana,
    is_rtl,
    isolate_runs,
    resolve_align,
    text_direction,
    text_lang,
    text_lines,
)

VECTORS: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[2] / "spec" / "direction" / "vectors.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", VECTORS["direction"], ids=lambda c: repr(c["text"])[:30])
def test_direction_vectors(case: dict[str, Any]) -> None:
    fallback = case.get("fallback")
    got = text_direction(case["text"], fallback) if fallback else text_direction(case["text"])
    assert got == case["dir"]
    assert text_lang(case["text"]) == case["lang"]


@pytest.mark.parametrize(
    "case", VECTORS["align"], ids=lambda c: f"{c['align']}-{c['default']}-{c['dir']}"
)
def test_align_vectors(case: dict[str, Any]) -> None:
    assert resolve_align(case["align"], case["default"], case["dir"]) == case["result"]
    assert explicit_align(case["align"], case["default"]) == case["explicit"]


@pytest.mark.parametrize("case", VECTORS["lines"], ids=lambda c: repr(c["text"])[:30])
def test_lines_vectors(case: dict[str, Any]) -> None:
    fallback = case.get("fallback")
    got = text_lines(case["text"], fallback) if fallback else text_lines(case["text"])
    assert [{"dir": line["dir"], "lang": line["lang"]} for line in got] == case["lines"]


def test_helpers() -> None:
    assert has_thaana("Name / ނަން") and not has_thaana("Name") and not has_thaana(None)
    assert is_rtl("ނަން / Name") and not is_rtl("Name / ނަން")


@pytest.mark.parametrize("case", VECTORS["isolate"], ids=lambda c: repr(c["text"])[:30])
def test_isolate_vectors(case: dict[str, Any]) -> None:
    got = isolate_runs(case["text"], case.get("dir"))
    assert [[t, d] for t, d in got] == case["runs"]


@pytest.mark.parametrize("case", VECTORS["bilingual"], ids=lambda c: repr(c["text"])[:30])
def test_bilingual_vectors(case: dict[str, Any]) -> None:
    assert bilingual_parts(case["text"]) == case["parts"]
