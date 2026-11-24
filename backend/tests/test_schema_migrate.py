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
    doc = _v1("en", _text("name", "Name"), _text("bio", "Bio"))
    out = upgrade_form(doc)
    assert out["schemaVersion"] == CURRENT == "2"
    assert "language" not in out["settings"]
    assert out["pages"] == doc["pages"]
    assert out["settings"] == {"title": "Form"}


def test_v1_keyboard_settings_are_dropped() -> None:
    doc = _v1(
        "dv",
        _text("a", "Name", inputScript="auto"),
        _text("b", "ނަން", inputScript="thaana"),
        _text("c", "Email", inputScript="latin"),
        {
            "kind": "section",
            "id": "s",
            "title": "ސެކްޝަން",
            "elements": [
                {
                    "kind": "field",
                    "id": "d",
                    "type": "long_text",
                    "label": "Notes",
                    "inputScript": "thaana",
                }
            ],
        },
        {"kind": "field", "id": "e", "type": "email", "label": "Email"},
        title="ފޯމު",
    )
    out = upgrade_form(doc)
    els = out["pages"][0]["elements"]
    assert all("inputScript" not in el for el in els)
    assert "inputScript" not in els[3]["elements"][0]
    assert els[1]["label"] == "ނަން"
    assert "language" not in out["settings"] and out["settings"]["title"] == "ފޯމު"
    assert doc["pages"][0]["elements"][0]["inputScript"] == "auto"  # input untouched


def test_v2_draft_with_a_keyboard_setting_is_cleaned() -> None:
    doc = {
        "schemaVersion": "2",
        "settings": {"title": "Form"},
        "pages": [{"id": "p1", "elements": [_text("a", "ނަން", inputScript="thaana")]}],
    }
    assert needs_upgrade(doc)
    out = upgrade_form(doc)
    assert "inputScript" not in out["pages"][0]["elements"][0]
    assert not needs_upgrade(out)
    Form.model_validate(doc)


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
    form = Form.model_validate(_v1("dv", _text("a", "Name", inputScript="auto"), title="ފޯމު"))
    dumped = form.dump()
    assert dumped["schemaVersion"] == "2"
    assert "language" not in dumped["settings"]
    assert "inputScript" not in dumped["pages"][0]["elements"][0]
