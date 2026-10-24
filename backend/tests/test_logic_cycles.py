"""Cycle detector fixtures (spec/logic/cycles). The same files run in vitest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.form import Form

CYCLE_DIR = Path(__file__).resolve().parents[2] / "spec" / "logic" / "cycles"
FIXTURES = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CYCLE_DIR.glob("*.json"))]


def _issue_codes(exc: ValidationError) -> list[str]:
    codes = []
    for err in exc.errors():
        for issue in (err.get("ctx") or {}).get("issues", []):
            codes.append(issue["code"])
    return codes


def test_fixtures_present() -> None:
    assert sum(f["expect"] == "cycle" for f in FIXTURES) >= 10


@pytest.mark.parametrize("fixture", FIXTURES, ids=[f["name"] for f in FIXTURES])
def test_cycle_fixture(fixture: dict[str, Any]) -> None:
    if fixture["expect"] == "ok":
        Form.model_validate(fixture["schema"])
        return
    with pytest.raises(ValidationError) as info:
        Form.model_validate(fixture["schema"])
    assert _issue_codes(info.value) == ["cycle"]
