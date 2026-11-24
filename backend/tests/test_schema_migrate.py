"""Upgrading stored form documents (app/schemas/migrate.py): schemaVersion 1 -> 2."""

from __future__ import annotations

import copy
from typing import Any

from app.schemas.form import Form
from app.schemas.migrate import CURRENT, needs_upgrade, upgrade_form


def _v1(language: str, *elements: dict[str, Any], title: str = "Form") -> dict[str, Any]:
    return {
        "schemaVersion": "1",
        "settings": {"language": language, "title": title},
        "pages": [{"id": "p1", "elements": list(elements)}],
    }


def _text(id: str, label: str, **kw: Any) -> dict[str, Any]:
    return {"kind": "field", "id": id, "type": "short_text", "label": label, **kw}


def test_v1_english_form_keeps_its_content() -> None:
    doc = _v1("en", _text("name", "Name"), _text("bio", "Bio", inputScript="auto"))
    out = upgrade_form(doc)
    assert out["schemaVersion"] == CURRENT == "2"
    assert "language" not in out["settings"]
    assert out["pages"] == doc["pages"]
    assert out["settings"] == {"title": "Form"}


def test_v1_dhivehi_form_keeps_the_thaana_keyboard() -> None:
    doc = _v1(
        "dv",
        _text("a", "Name"),  # auto + Latin label: was Thaana because of the form language
        _text("b", "ނަން"),  # auto + Thaana label: auto still turns the keyboard on
        _text("c", "Email", inputScript="latin"),
        {
            "kind": "section",
            "id": "s",
            "title": "ސެކްޝަން",
            "elements": [{"kind": "field", "id": "d", "type": "long_text", "label": "Notes"}],
        },
        {"kind": "field", "id": "e", "type": "email", "label": "Email"},
        title="ފޯމު",
    )
    out = upgrade_form(doc)
    els = out["pages"][0]["elements"]
    assert els[0]["inputScript"] == "thaana"
    assert els[1].get("inputScript", "auto") == "auto"
    assert els[2]["inputScript"] == "latin"
    assert els[3]["elements"][0]["inputScript"] == "thaana"
    assert "inputScript" not in els[4]
    assert "language" not in out["settings"] and out["settings"]["title"] == "ފޯމު"


def test_upgrade_is_idempotent_and_does_not_mutate() -> None:
    doc = _v1("dv", _text("a", "Name"))
    before = copy.deepcopy(doc)
    once = upgrade_form(doc)
    assert doc == before
    assert not needs_upgrade(once)
    assert upgrade_form(once) is once
    assert upgrade_form(copy.deepcopy(once)) == once


def test_unversioned_document_with_language_is_upgraded() -> None:
    doc = _v1("en", _text("a", "Name"))
    del doc["schemaVersion"]
    assert needs_upgrade(doc)
    assert "language" not in upgrade_form(doc)["settings"]


def test_form_accepts_v1_documents() -> None:
    form = Form.model_validate(_v1("dv", _text("a", "Name"), title="ފޯމު"))
    dumped = form.dump()
    assert dumped["schemaVersion"] == "2"
    assert "language" not in dumped["settings"]
    assert dumped["pages"][0]["elements"][0]["inputScript"] == "thaana"
