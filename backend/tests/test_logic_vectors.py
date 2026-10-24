"""Shared logic conformance suite (spec/logic/vectors). The same files run in vitest.

Vector file format::

    {"name", "description", "schema": <form>, "cases": [{"name", "answers", "expect"}]}

``expect`` keys are all optional:

* ``visible`` / ``hidden``: every listed top-level element id has that state;
* ``required`` / ``notRequired``: every listed field id is (not) required;
* ``path``: the exact page path;
* ``strippedAnswers``: the exact stripped answers;
* ``rows``: ``{repeaterId: [ {visible, hidden, required, notRequired}, ... ]}`` with the
  exact number of rows, per-row lists checked like the top-level ones.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.logic.engine import Evaluation, RowResult, evaluate
from app.schemas.form import Form

VECTOR_DIR = Path(__file__).resolve().parents[2] / "spec" / "logic" / "vectors"
MIN_VECTORS = 150


def _load() -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    out = []
    for path in sorted(VECTOR_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for case in data["cases"]:
            out.append((f"{path.stem}: {case['name']}", data["schema"], case))
    return out


VECTORS = _load()
_FORMS: dict[str, Form] = {}


def _form(schema: dict[str, Any]) -> Form:
    key = json.dumps(schema, sort_keys=True)
    if key not in _FORMS:
        _FORMS[key] = Form.model_validate(schema)
    return _FORMS[key]


def _check_lists(
    where: str,
    expect: dict[str, Any],
    visible: list[str],
    hidden: list[str],
    required: list[str],
) -> None:
    for el in expect.get("visible", []):
        assert el in visible, f"{where}: expected '{el}' visible"
    for el in expect.get("hidden", []):
        assert el in hidden, f"{where}: expected '{el}' hidden"
    for el in expect.get("required", []):
        assert el in required, f"{where}: expected '{el}' required"
    for el in expect.get("notRequired", []):
        assert el not in required, f"{where}: expected '{el}' not required"


def check(result: Evaluation, expect: dict[str, Any]) -> None:
    _check_lists("top level", expect, result.visible, result.hidden, result.required)
    if "path" in expect:
        assert result.path == expect["path"]
    if "strippedAnswers" in expect:
        assert result.stripped_answers == expect["strippedAnswers"]
    for rep, rows in expect.get("rows", {}).items():
        actual: list[RowResult] = result.rows.get(rep, [])
        assert len(actual) == len(rows), f"repeater '{rep}': row count"
        for i, (exp_row, row) in enumerate(zip(rows, actual, strict=True)):
            _check_lists(f"{rep}[{i}]", exp_row, row.visible, row.hidden, row.required)


def test_vector_count() -> None:
    assert len(VECTORS) >= MIN_VECTORS, f"only {len(VECTORS)} logic vectors"


@pytest.mark.parametrize(("name", "schema", "case"), VECTORS, ids=[v[0] for v in VECTORS])
def test_logic_vector(name: str, schema: dict[str, Any], case: dict[str, Any]) -> None:
    check(evaluate(_form(schema), case["answers"]), case["expect"])
