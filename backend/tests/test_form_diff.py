"""Review changes: the structured diff between the live version and the draft (form_diff)."""

from __future__ import annotations

import copy
from typing import Any

from app.services.form_diff import diff, interleave, iter_changes, plain


def f(fid: str, type_: str = "short_text", **extra: Any) -> dict[str, Any]:
    return {"kind": "field", "id": fid, "type": type_, "label": fid.title(), **extra}


def choice(fid: str, *opts: tuple[str, str], type_: str = "single_choice") -> dict[str, Any]:
    return f(fid, type_, options=[{"value": v, "label": label} for v, label in opts])


def form(*pages: list[dict[str, Any]], **settings: Any) -> dict[str, Any]:
    return {
        "schemaVersion": "1",
        "settings": {"title": "T", **settings},
        "pages": [{"id": f"p{i + 1}", "elements": els} for i, els in enumerate(pages)],
    }


def by_id(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {e["id"]: e for e in iter_changes(result)}


def props(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["property"]: c for c in entry["changes"]}


def test_no_changes_and_defaults_compare_equal() -> None:
    a = form([f("name")])
    b = form([f("name", required=False, width="full")])
    result = diff(a, b)
    assert result["hasChanges"] is False
    assert result["summary"] == "No changes"
    assert result["pages"] == [] and result["settings"] == []


def test_question_added_and_removed_keep_their_place() -> None:
    a = form([f("a"), f("b"), f("c")])
    b = form([f("a"), f("new"), f("c")])
    result = diff(a, b)
    page = result["pages"][0]
    assert page["status"] is None and page["pageId"] == "p1"
    # The removed one sits where it was (after "a"), the added one where it is now.
    assert [(e["id"], e["status"]) for e in page["elements"]] == [
        ("b", "removed"),
        ("new", "added"),
    ]
    assert result["counts"] == {"added": 1, "removed": 1, "changed": 0, "moved": 0}
    assert result["summary"] == "1 question added, 1 question removed"
    entry = by_id(result)["new"]
    assert entry["typeName"] == "Short answer" and entry["summary"] == "Short answer added"


def test_text_properties() -> None:
    a = form([f("name", description="Old help")])
    b = form([f("name", label="Full name", placeholder="e.g. Aminath", description="New help")])
    changes = props(by_id(diff(a, b))["name"])
    assert changes["label"]["summary"] == "Label changed"
    assert changes["label"]["before"] == [{"text": "Name", "content": True}]
    assert changes["label"]["after"] == [{"text": "Full name", "content": True}]
    assert changes["placeholder"]["summary"] == "Placeholder added"
    assert changes["placeholder"]["before"] is None
    assert changes["description"]["name"] == "Help text"
    assert changes["description"]["summary"] == "Help text changed"


def test_text_removed() -> None:
    a = form([f("name", description="Help")])
    b = form([f("name")])
    change = props(by_id(diff(a, b))["name"])["description"]
    assert change["summary"] == "Help text removed" and change["after"] is None


def test_required_width_and_validation() -> None:
    a = form([f("code", maxLength=10)])
    b = form([f("code", required=True, width="half", maxLength=12, pattern="^[A-Z]+$")])
    changes = props(by_id(diff(a, b))["code"])
    assert changes["required"]["summary"] == "Now required"
    assert plain(changes["required"]["before"]) == "Off"
    assert plain(changes["required"]["after"]) == "On"
    assert plain(changes["width"]["before"]) == "Full width"
    assert plain(changes["width"]["after"]) == "Half width"
    assert changes["maxLength"]["summary"] == "Max length changed"
    assert plain(changes["maxLength"]["after"]) == "12"
    assert changes["pattern"]["summary"] == "Pattern added"
    back = props(by_id(diff(b, a))["code"])
    assert back["required"]["summary"] == "No longer required"


def test_type_change() -> None:
    a = form([f("notes")])
    b = form([f("notes", "long_text")])
    change = props(by_id(diff(a, b))["notes"])["type"]
    assert change["summary"] == "Question type changed"
    assert plain(change["before"]) == "Short answer" and plain(change["after"]) == "Long answer"


def test_options_added_removed_renamed_reordered() -> None:
    a = form([choice("colour", ("r", "Red"), ("g", "Green"), ("b", "Blue"))])
    b = form([choice("colour", ("b", "Blue"), ("r", "Crimson"), ("y", "Yellow"))])
    change = props(by_id(diff(a, b))["colour"])["options"]
    opts = change["options"]
    assert opts["added"] == [{"value": "y", "label": "Yellow"}]
    assert opts["removed"] == [{"value": "g", "label": "Green"}]
    assert opts["renamed"] == [{"value": "r", "before": "Red", "after": "Crimson"}]
    assert opts["reordered"] is True
    assert change["summary"] == (
        "1 option added, 1 option removed, 1 option renamed, options reordered"
    )


def test_options_only_reordered() -> None:
    a = form([choice("c", ("1", "One"), ("2", "Two"))])
    b = form([choice("c", ("2", "Two"), ("1", "One"))])
    assert props(by_id(diff(a, b))["c"])["options"]["summary"] == "Options reordered"


def test_logic_rules_in_words() -> None:
    age = f("age", "number")
    yes = f("kids", "yes_no")
    a = form([age, yes, f("school")])
    cond = {
        "all": [
            {"field": "age", "op": "lt", "value": 18},
            {"field": "kids", "op": "eq", "value": True},
        ]
    }
    b = form(
        [age, yes, f("school", visibleIf=cond, requiredIf={"field": "age", "op": "not_empty"})]
    )
    changes = props(by_id(diff(a, b))["school"])
    assert changes["visibleIf"]["summary"] == "Show rule added"
    assert changes["visibleIf"]["name"] == "Shown when"
    assert plain(changes["visibleIf"]["after"]) == "Age is less than 18 and Kids is Yes"
    assert changes["requiredIf"]["summary"] == "Required rule added"
    assert plain(changes["requiredIf"]["after"]) == "Age is not empty"
    # Labels are form content, operator words are not.
    assert {"text": "Age", "content": True} in changes["visibleIf"]["after"]
    assert {"text": " is less than", "content": False} in changes["visibleIf"]["after"]

    c = copy.deepcopy(b)
    c["pages"][0]["elements"][2]["visibleIf"] = {"field": "age", "op": "gte", "value": 18}
    change = props(by_id(diff(b, c))["school"])["visibleIf"]
    assert change["summary"] == "Show rule changed"
    assert plain(change["after"]) == "Age is at least 18"


def test_choice_values_shown_by_label() -> None:
    region = choice("region", ("male", "Malé"), ("addu", "Addu"))
    a = form([region, f("ferry")])
    cond = {"field": "region", "op": "in", "value": ["male", "addu"]}
    b = form([region, f("ferry", visibleIf=cond)])
    change = props(by_id(diff(a, b))["ferry"])["visibleIf"]
    assert plain(change["after"]) == "Region is one of Malé or Addu"


def test_moved_within_a_page() -> None:
    a = form([f("a"), f("b"), f("c")])
    b = form([f("c"), f("a"), f("b")])
    result = diff(a, b)
    entries = by_id(result)
    assert list(entries) == ["c"]
    assert entries["c"]["status"] == "moved"
    assert entries["c"]["summary"] == "Moved to a new position"
    assert result["counts"]["moved"] == 1


def test_moved_to_another_page_and_changed() -> None:
    a = form([f("a"), f("b")], [f("c")])
    a["pages"][1]["title"] = "Contact"
    b = copy.deepcopy(a)
    moved = b["pages"][0]["elements"].pop(1)
    moved["label"] = "B2"
    b["pages"][1]["elements"].append(moved)
    result = diff(a, b)
    entry = by_id(result)["b"]
    assert entry["status"] == "changed"
    assert plain(entry["movedFrom"]) == "Page 1"
    assert entry["summary"] == "Label changed; Moved from Page 1"
    # Reported under the page it is on now.
    assert [p["pageId"] for p in result["pages"]] == ["p2"]
    assert result["pages"][0]["title"] == "Contact"
    assert result["counts"] == {"added": 0, "removed": 0, "changed": 1, "moved": 1}


def test_moved_into_a_section() -> None:
    a = form([f("a"), {"kind": "section", "id": "s", "title": "Address", "elements": []}])
    b = form([{"kind": "section", "id": "s", "title": "Address", "elements": [f("a")]}])
    entry = by_id(diff(a, b))["a"]
    assert entry["status"] == "moved"
    assert entry["within"] == ["Address"]
    assert plain(entry["movedFrom"]) == "Page 1"


def test_repeater_children_and_settings() -> None:
    rep = {
        "kind": "repeater",
        "id": "people",
        "label": "People",
        "minRows": 1,
        "elements": [f("person_name"), f("person_email", "email")],
    }
    a = form([rep])
    b = copy.deepcopy(a)
    r = b["pages"][0]["elements"][0]
    r["maxRows"] = 5
    r["description"] = "Everyone involved"
    r["elements"][0]["required"] = True
    r["elements"].pop(1)
    r["elements"].append(f("person_phone", "phone"))
    result = diff(a, b)
    entries = by_id(result)
    rep_changes = props(entries["people"])
    assert rep_changes["maxRows"]["summary"] == "Maximum rows added"
    assert rep_changes["description"]["name"] == "Description"
    assert entries["person_name"]["within"] == ["People"]
    assert props(entries["person_name"])["required"]["summary"] == "Now required"
    assert entries["person_email"]["status"] == "removed"
    assert entries["person_email"]["within"] == ["People"]
    assert entries["person_phone"]["status"] == "added"
    assert result["summary"] == (
        "1 question added, 1 question removed, 1 question changed, 1 repeater changed"
    )


def test_pages_added_removed_moved_and_titled() -> None:
    a = form([f("a")], [f("b")], [f("c")])
    b = copy.deepcopy(a)
    p1, p2, p3 = b["pages"]
    p2["title"] = "Second"
    b["pages"] = [p1, p3, {"id": "p4", "title": "Page 4", "elements": []}]
    result = diff(a, b)
    pages = {p["pageId"]: p for p in result["pages"]}
    assert pages["p2"]["status"] == "removed"
    assert pages["p2"]["number"] == 2
    assert [e["id"] for e in pages["p2"]["elements"]] == ["b"]
    assert pages["p4"]["status"] == "added" and pages["p4"]["summary"] == "Page added"
    assert "p3" not in pages  # only its number changed: that is not a move
    assert [p["pageId"] for p in result["pages"]] == ["p2", "p4"]

    c = copy.deepcopy(a)
    c["pages"] = [c["pages"][2], c["pages"][0], c["pages"][1]]
    c["pages"][1]["title"] = "Start"
    result = diff(a, c)
    pages = {p["pageId"]: p for p in result["pages"]}
    assert pages["p3"]["status"] == "moved"
    assert pages["p3"]["movedFrom"] == 3
    assert pages["p3"]["summary"] == "Page moved (was page 3)"
    assert pages["p1"]["status"] == "changed"
    assert pages["p1"]["changes"][0]["name"] == "Page title"


def test_empty_pages_added_like_a_double_click_on_add_page() -> None:
    a = form([f("a")])
    b = copy.deepcopy(a)
    b["pages"] += [
        {"id": "page_2", "title": "Page 2", "elements": []},
        {"id": "page_3", "title": "Page 3", "elements": []},
    ]
    result = diff(a, b)
    assert result["summary"] == "2 pages added"
    assert [p["status"] for p in result["pages"]] == ["added", "added"]


def test_page_navigation_rules() -> None:
    a = form([f("age", "number")], [f("b")], [f("c")])
    a["pages"][2]["title"] = "Adults"
    b = copy.deepcopy(a)
    b["pages"][0]["next"] = [{"if": {"field": "age", "op": "gte", "value": 18}, "goto": "p3"}]
    result = diff(a, b)
    change = result["pages"][0]["changes"][0]
    assert change["summary"] == "Page navigation added"
    assert plain(change["after"]) == "If Age is at least 18, go to Adults"


def test_form_settings() -> None:
    a = form([f("a")])
    b = form([f("a")], title="New", submitLabel="Send", successMessage="Thanks")
    b["settings"]["theme"] = {"accent": "#112233"}
    result = diff(a, b)
    names = {c["property"]: c for c in result["settings"]}
    assert names["title"]["summary"] == "Form title changed"
    assert names["submitLabel"]["summary"] == "Submit button text added"
    assert names["successMessage"]["summary"] == "Message after submitting added"
    assert names["theme.accent"]["summary"] == "Accent colour added"
    assert result["summary"] == "4 form settings changed"
    assert result["counts"]["changed"] == 4


def test_content_blocks_and_dhivehi() -> None:
    a = form(
        [{"kind": "content", "id": "h", "contentType": "heading", "text": "ފުރަތަމަ"}], language="dv"
    )
    b = form(
        [{"kind": "content", "id": "h", "contentType": "heading", "text": "ދެވަނަ"}], language="dv"
    )
    result = diff(a, b)
    assert result["language"] == "dv"
    entry = by_id(result)["h"]
    assert entry["label"] == "ދެވަނަ"
    assert entry["typeName"] == "Heading"
    change = props(entry)["text"]
    assert change["before"] == [{"text": "ފުރަތަމަ", "content": True}]
    assert result["summary"] == "1 content block changed"


def test_interleave_puts_removed_items_back() -> None:
    assert interleave(["a", "c"], ["a", "b", "c"], ["b"]) == ["a", "b", "c"]
    assert interleave(["c"], ["a", "b", "c"], ["a", "b"]) == ["a", "b", "c"]
    assert interleave(["x"], ["a"], ["a"]) == ["a", "x"]
