"""AI schema tools: every tool, validation failures and the checks they rely on."""

from __future__ import annotations

from typing import Any

import pytest

from app.ai.tools import TOOLS, WorkingCopy, slug_id, tool_specs
from app.schemas.form import Form


def base(language: str = "en") -> dict[str, Any]:
    return Form.model_validate(
        {
            "settings": {"language": language, "title": "Volunteers"},
            "pages": [
                {
                    "id": "page_1",
                    "elements": [
                        {"kind": "field", "id": "name", "type": "short_text", "label": "Name"},
                        {"kind": "field", "id": "email", "type": "email", "label": "Email"},
                        {
                            "kind": "field",
                            "id": "has_car",
                            "type": "yes_no",
                            "label": "Do you have a car?",
                        },
                        {
                            "kind": "section",
                            "id": "car",
                            "title": "Car",
                            "visibleIf": {"field": "has_car", "op": "eq", "value": True},
                            "elements": [
                                {
                                    "kind": "field",
                                    "id": "plate",
                                    "type": "short_text",
                                    "label": "Plate",
                                }
                            ],
                        },
                    ],
                },
                {"id": "page_2", "title": "More", "elements": []},
            ],
        }
    ).dump()


def wc(language: str = "en") -> WorkingCopy:
    return WorkingCopy(base(language))


def ids(w: WorkingCopy, page: int = 0) -> list[str]:
    return [e["id"] for e in w.schema["pages"][page]["elements"]]


def test_specs_cover_every_tool_and_are_portable() -> None:
    names = {s.name for s in tool_specs()}
    assert names == set(TOOLS) - {"report_filled_in"}
    assert "report_filled_in" in {s.name for s in tool_specs(importing=True)}
    for spec in tool_specs(importing=True):
        assert spec.parameters["type"] == "object"
        assert spec.description
        text = str(spec.parameters)
        assert "$ref" not in text and "$defs" not in text
        assert "'title': 'NavigationRuleArg'" not in text
    add = next(s for s in tool_specs() if s.name == "add_field")
    assert set(add.parameters["required"]) == {"parentId", "field"}


def test_get_form_returns_the_working_copy() -> None:
    w = wc()
    step = w.run("get_form", {})
    assert step.ok and step.result["form"] == w.schema and not step.changed


def test_add_field_makes_ids_options_and_validates() -> None:
    w = wc()
    step = w.run(
        "add_field",
        {
            "parentId": "page_1",
            "index": 2,
            "field": {
                "type": "single_choice",
                "label": "T-shirt size",
                "required": True,
                "options": ["Small", "Medium", {"label": "Large", "value": "l"}],
            },
        },
    )
    assert step.ok, step.error
    assert step.result == {"id": "t_shirt_size"} and step.action == "Added"
    assert ids(w)[2] == "t_shirt_size"
    field = w.schema["pages"][0]["elements"][2]
    assert field["kind"] == "field"
    assert [o["value"] for o in field["options"]] == ["small", "medium", "l"]
    # A second question with the same label gets a unique id.
    step = w.run("add_field", {"parentId": "page_1", "field": {"type": "email", "label": "Email"}})
    assert step.result == {"id": "email_2"}


def test_add_field_dhivehi_label_gets_a_type_based_id() -> None:
    w = wc("dv")
    step = w.run(
        "add_field",
        {"parentId": "page_2", "field": {"type": "phone", "label": "ފޯނު ނަންބަރު"}},
    )
    assert step.ok and step.result == {"id": "phone"}
    assert w.schema["pages"][1]["elements"][0]["label"] == "ފޯނު ނަންބަރު"


def test_add_field_into_section_and_nested_elements() -> None:
    w = wc()
    step = w.run(
        "add_field",
        {
            "parentId": "page_2",
            "field": {
                "kind": "repeater",
                "label": "Children",
                "elements": [
                    {"type": "short_text", "label": "Name"},
                    {"type": "date", "label": "Born"},
                ],
            },
        },
    )
    assert step.ok, step.error
    rep = w.schema["pages"][1]["elements"][0]
    assert [e["id"] for e in rep["elements"]] == ["name_2", "born"]
    step = w.run("add_field", {"parentId": "car", "field": {"type": "number", "label": "Seats"}})
    assert step.ok
    assert [e["id"] for e in w.schema["pages"][0]["elements"][3]["elements"]] == ["plate", "seats"]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({"parentId": "nowhere", "field": {"type": "email", "label": "x"}}, "no page, section"),
        ({"parentId": "email", "field": {"type": "email", "label": "x"}}, "can only go into"),
        ({"parentId": "page_1", "field": {"label": "x"}}, '"kind"'),
        ({"parentId": "page_1", "field": {"type": "telepathy", "label": "x"}}, "not be valid"),
        (
            {"parentId": "page_1", "field": {"type": "number", "label": "x", "min": 5, "max": 1}},
            "min must not exceed max",
        ),
        (
            {
                "parentId": "page_1",
                "field": {"kind": "content", "contentType": "image", "imageFileId": "f"},
            },
            "Images",
        ),
        ({"field": {"type": "email", "label": "x"}}, "Invalid arguments"),
        ({"parentId": "page_1", "field": {"type": "email", "label": "x"}, "extra": 1}, "Invalid"),
    ],
)
def test_add_field_failures_leave_the_copy_alone(args: dict[str, Any], message: str) -> None:
    w = wc()
    before = w.schema
    step = w.run("add_field", args)
    assert not step.ok and step.error and message in step.error, step.error
    assert w.schema == before and not step.changed


def test_signature_in_repeater_is_rejected_by_schema_rules() -> None:
    w = wc()
    w.run(
        "add_field",
        {"parentId": "page_2", "field": {"kind": "repeater", "id": "rows", "label": "Rows"}},
    )
    step = w.run("add_field", {"parentId": "rows", "field": {"type": "signature", "label": "Sign"}})
    assert not step.ok and "not be valid" in (step.error or "")


def test_update_field_changes_and_removes_props() -> None:
    w = wc()
    step = w.run(
        "update_field",
        {
            "id": "name",
            "changes": {"required": True, "description": "As on your ID", "max_length": 80},
        },
    )
    assert step.ok, step.error
    el = w.schema["pages"][0]["elements"][0]
    assert el["required"] and el["description"] == "As on your ID" and el["maxLength"] == 80
    step = w.run("update_field", {"id": "name", "changes": {"description": None}})
    assert step.ok and "description" not in w.schema["pages"][0]["elements"][0]
    # Changing the type is allowed when the result is valid.
    step = w.run(
        "update_field", {"id": "name", "changes": {"type": "long_text", "maxLength": None}}
    )
    assert step.ok and w.schema["pages"][0]["elements"][0]["type"] == "long_text"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"id": "full_name"}, "can't be changed"),
        ({"kind": "content"}, "can't be changed"),
        ({"elements": []}, "can't be changed"),
        ({}, "at least one"),
        ({"options": [{"value": "a", "label": "A"}]}, "not be valid"),
        ({"visibleIf": {"field": "nope", "op": "not_empty"}}, "not be valid"),
    ],
)
def test_update_field_failures(changes: dict[str, Any], message: str) -> None:
    w = wc()
    step = w.run("update_field", {"id": "name", "changes": changes})
    assert not step.ok and message in (step.error or ""), step.error


def test_remove_field_blocked_by_references() -> None:
    w = wc()
    step = w.run("remove_field", {"id": "has_car"})
    assert not step.ok
    assert step.result["referencedBy"] == ["car"]
    # Removing the section (and the logic with it) first makes it possible.
    assert w.run("remove_field", {"id": "car"}).ok
    step = w.run("remove_field", {"id": "has_car"})
    assert step.ok and ids(w) == ["name", "email"]
    assert not w.run("remove_field", {"id": "has_car"}).ok


def test_move_field_between_containers_and_pages() -> None:
    w = wc()
    step = w.run("move_field", {"id": "email", "parentId": "page_1", "index": 0})
    assert step.ok and ids(w)[:2] == ["email", "name"]
    step = w.run("move_field", {"id": "name", "parentId": "page_2"})
    assert step.ok and ids(w, 1) == ["name"]
    assert not w.run("move_field", {"id": "car", "parentId": "car"}).ok
    # Page logic may only read earlier pages: moving the question it reads onto that page fails.
    cond = {"field": "has_car", "op": "eq", "value": True}
    assert w.run("set_logic", {"targetId": "page_2", "kind": "visibleIf", "condition": cond}).ok
    step = w.run("move_field", {"id": "has_car", "parentId": "page_2"})
    assert not step.ok and "not be valid" in (step.error or "")


def test_set_options() -> None:
    w = wc()
    w.run(
        "add_field",
        {
            "parentId": "page_2",
            "field": {"id": "size", "type": "multi_choice", "label": "Size", "options": ["S"]},
        },
    )
    step = w.run("set_options", {"id": "size", "options": ["Small", "Large"]})
    assert step.ok and [o["label"] for o in step.result["options"]] == ["Small", "Large"]
    assert not w.run("set_options", {"id": "name", "options": ["a"]}).ok
    assert not w.run("set_options", {"id": "size", "options": []}).ok
    step = w.run(
        "set_options",
        {"id": "size", "options": [{"value": "a", "label": "A"}, {"value": "a", "label": "B"}]},
    )
    assert not step.ok and "unique" in (step.error or "")


def test_set_logic_and_cycles() -> None:
    w = wc()
    cond = {"field": "has_car", "op": "eq", "value": True}
    assert w.run(
        "set_logic",
        {
            "targetId": "email",
            "kind": "requiredIf",
            "condition": {"field": "name", "op": "not_empty"},
        },
    ).ok
    assert w.schema["pages"][0]["elements"][1]["requiredIf"]["field"] == "name"
    assert w.run("set_logic", {"targetId": "page_2", "kind": "visibleIf", "condition": cond}).ok
    assert not w.run(
        "set_logic", {"targetId": "page_2", "kind": "requiredIf", "condition": cond}
    ).ok
    assert not w.run("set_logic", {"targetId": "car", "kind": "requiredIf", "condition": cond}).ok
    # A question can't depend on itself.
    step = w.run("set_logic", {"targetId": "has_car", "kind": "visibleIf", "condition": cond})
    assert not step.ok
    # Two questions that depend on each other form a cycle.
    first = {"field": "email", "op": "not_empty"}
    assert w.run("set_logic", {"targetId": "name", "kind": "visibleIf", "condition": first}).ok
    second = {"field": "name", "op": "not_empty"}
    step = w.run("set_logic", {"targetId": "email", "kind": "visibleIf", "condition": second})
    assert not step.ok and "cycle" in (step.error or "").lower(), step.error
    assert w.run("set_logic", {"targetId": "email", "kind": "requiredIf", "condition": None}).ok
    assert "requiredIf" not in w.schema["pages"][0]["elements"][1]
    step = w.run(
        "set_logic",
        {"targetId": "car", "kind": "visibleIf", "condition": {"field": "has_car", "op": "bogus"}},
    )
    assert not step.ok


def test_pages() -> None:
    w = wc()
    step = w.run("add_page", {"title": "Intro", "afterPageId": "page_1"})
    assert step.ok and step.result == {"pageId": "page_3"}
    assert [p["id"] for p in w.schema["pages"]] == ["page_1", "page_3", "page_2"]
    assert w.run("update_page", {"pageId": "page_3", "description": "Hello"}).ok
    assert w.run("update_page", {"pageId": "page_3", "title": None}).ok
    assert "title" not in w.schema["pages"][1]
    assert not w.run("update_page", {"pageId": "page_9", "title": "x"}).ok
    step = w.run("remove_page", {"pageId": "page_1"})
    assert not step.ok and "moveElementsTo" in (step.error or "")
    assert w.run("remove_page", {"pageId": "page_1", "moveElementsTo": "page_2"}).ok
    assert [p["id"] for p in w.schema["pages"]] == ["page_3", "page_2"]
    assert w.run("remove_page", {"pageId": "page_3"}).ok
    assert not w.run("remove_page", {"pageId": "page_2"}).ok  # the last page stays


def test_page_navigation() -> None:
    w = wc()
    w.run("add_page", {"title": "Car details"})
    rules = [{"if": {"field": "has_car", "op": "eq", "value": False}, "goto": "submit"}]
    assert w.run("set_page_navigation", {"pageId": "page_1", "rules": rules}).ok
    assert w.schema["pages"][0]["next"][0]["goto"] == "submit"
    back = [{"if": {"field": "has_car", "op": "eq", "value": True}, "goto": "page_1"}]
    assert not w.run("set_page_navigation", {"pageId": "page_2", "rules": back}).ok
    assert w.run("set_page_navigation", {"pageId": "page_1", "rules": []}).ok
    assert "next" not in w.schema["pages"][0]


def test_update_settings() -> None:
    w = wc()
    assert w.run("update_settings", {"title": "Helpers", "submitLabel": "Send"}).ok
    assert w.schema["settings"]["title"] == "Helpers"
    assert w.schema["settings"]["submitLabel"] == "Send"
    assert w.run("update_settings", {"submitLabel": None}).ok
    assert "submitLabel" not in w.schema["settings"]
    assert not w.run("update_settings", {"title": None}).ok
    # The language and theme are not the assistant's to change.
    assert not w.run("update_settings", {"language": "dv"}).ok
    assert not w.run("update_settings", {"theme": {"accent": "#000000"}}).ok


def test_flags_and_filled_in() -> None:
    w = WorkingCopy(base(), importing=True)
    assert w.run("flag_uncertain", {"targetId": "email", "note": "Smudged"}).ok
    assert w.run("flag_uncertain", {"targetId": "email", "note": "Hard to read"}).ok
    assert w.flags == [{"targetId": "email", "note": "Hard to read"}]
    assert not w.run("flag_uncertain", {"targetId": "nope", "note": "x"}).ok
    step = w.run("report_filled_in", {"note": "Answers are written in"})
    assert step.ok and w.filled_in == "Answers are written in"
    # Outside an import the tool doesn't exist.
    assert not wc().run("report_filled_in", {"note": "x"}).ok


def test_unknown_tool() -> None:
    step = wc().run("drop_database", {})
    assert not step.ok and "Unknown tool" in step.result["error"]


def test_slug_id() -> None:
    assert slug_id("Date of birth", "date") == "date_of_birth"
    assert slug_id("2nd phone", "phone") == "phone"
    assert slug_id("ނަން", "short_text") == "short_text"
