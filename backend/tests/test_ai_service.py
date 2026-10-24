"""Suggestion helpers: the change list, language checks and the guarded (rebased) patch."""

from __future__ import annotations

import copy

import jsonpatch
import pytest

from app.ai.service import changes, guarded_patch, language_flags
from app.ai.tools import WorkingCopy
from tests.test_ai_tools import base


def test_change_list() -> None:
    old = base()
    w = WorkingCopy(copy.deepcopy(old))
    assert w.run("update_settings", {"title": "New"}).ok
    assert w.run("update_field", {"id": "name", "changes": {"required": True}}).ok
    assert w.run("move_field", {"id": "email", "parentId": "page_1", "index": 0}).ok
    assert w.run("remove_field", {"id": "plate"}).ok
    assert w.run("add_page", {"title": "Extra"}).ok
    assert w.run(
        "add_field", {"parentId": "page_3", "field": {"type": "phone", "label": "Phone"}}
    ).ok
    got = {(c["kind"], c["id"], c["change"]) for c in changes(old, w.schema)}
    assert got == {
        ("settings", None, "changed"),
        ("element", "name", "changed"),
        ("element", "email", "moved"),
        ("element", "plate", "removed"),
        ("page", "page_3", "added"),
        ("element", "phone", "added"),
    }
    assert changes(old, old) == []


def test_language_flags() -> None:
    dv = base("dv")
    w = WorkingCopy(copy.deepcopy(dv))
    w.run(
        "add_field", {"parentId": "page_2", "field": {"id": "a", "type": "email", "label": "Email"}}
    )
    w.run(
        "add_field", {"parentId": "page_2", "field": {"id": "b", "type": "email", "label": "އީމެއިލް"}}
    )
    flags = language_flags(w.schema, changes(dv, w.schema), "dv")
    assert [f["targetId"] for f in flags] == ["a"]
    en = base()
    w = WorkingCopy(copy.deepcopy(en))
    w.run(
        "add_field", {"parentId": "page_2", "field": {"id": "c", "type": "email", "label": "އީމެއިލް"}}
    )
    assert [f["targetId"] for f in language_flags(w.schema, changes(en, w.schema), "en")] == ["c"]


def test_guarded_patch_applies_to_unrelated_edits_and_refuses_clashes() -> None:
    old = base()
    w = WorkingCopy(copy.deepcopy(old))
    w.run("add_field", {"parentId": "page_2", "field": {"type": "phone", "label": "Phone"}})
    patch = guarded_patch(old, w.schema)
    assert any(op["op"] == "test" for op in patch)
    # Someone renamed a question on page 1: the page-2 suggestion still fits.
    other = copy.deepcopy(old)
    other["pages"][0]["elements"][0]["label"] = "Your name"
    merged = jsonpatch.apply_patch(other, patch)
    assert merged["pages"][0]["elements"][0]["label"] == "Your name"
    assert merged["pages"][1]["elements"][0]["id"] == "phone"
    # Someone added a question on page 2 too: the lists differ, so it's a clash.
    clash = copy.deepcopy(old)
    clash["pages"][1]["elements"].append(
        {"kind": "field", "id": "x", "type": "email", "label": "X"}
    )
    with pytest.raises(jsonpatch.JsonPatchTestFailed):
        jsonpatch.apply_patch(clash, patch)
    # Unchanged base: the patch gives exactly the suggestion.
    assert jsonpatch.apply_patch(old, patch) == w.schema
