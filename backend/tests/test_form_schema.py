from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.export import main as export_main
from app.schemas.export import render
from app.schemas.form import Form, text_direction
from app.schemas.rules import collect_publish_issues

EXAMPLE_PATH = Path(__file__).resolve().parents[2] / "spec" / "examples" / "youth-programme.json"
EXAMPLE: dict[str, Any] = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def fld(id: str, type: str = "short_text", **kw: Any) -> dict[str, Any]:
    return {"kind": "field", "id": id, "type": type, "label": id, **kw}


def form(*elements: dict[str, Any], **page_kw: Any) -> dict[str, Any]:
    return {
        "schemaVersion": "1",
        "settings": {"title": "T"},
        "pages": [{"id": "p1", "elements": list(elements), **page_kw}],
    }


def codes(data: dict[str, Any]) -> list[str]:
    with pytest.raises(ValidationError) as info:
        Form.model_validate(data)
    out: list[str] = []
    for err in info.value.errors():
        issues = (err.get("ctx") or {}).get("issues")
        if issues:
            out.extend(i["code"] for i in issues)
        else:
            out.append(err["type"])
    return out


def test_design_example_is_valid_and_round_trips() -> None:
    parsed = Form.model_validate(EXAMPLE)
    dumped = parsed.dump()
    assert dumped["settings"]["language"] == "dv"
    assert dumped["pages"][0]["elements"][1]["patternMessage"] == "ފޯމެޓް: A123456"
    assert Form.model_validate(dumped) == parsed


def test_language_defaults_to_en_and_sets_direction() -> None:
    parsed = Form.model_validate(form(fld("a")))
    assert parsed.settings.language == "en"
    assert "language" not in parsed.dump()["settings"]
    assert text_direction(parsed.settings.language) == "ltr"
    assert text_direction(Form.model_validate(EXAMPLE).settings.language) == "rtl"


def test_only_en_and_dv_languages() -> None:
    data = form(fld("a"))
    data["settings"]["language"] = "fr"
    assert "literal_error" in codes(data)


def test_bilingual_text_objects_rejected() -> None:
    assert "string_type" in codes(form({**fld("a"), "label": {"en": "Name", "dv": "ނަން"}}))


def test_snake_case_input_is_accepted() -> None:
    data = form(fld("a", visible_if={"field": "b", "op": "empty"}), fld("b"))
    data["settings"] = {"language": "en", "title": "T", "submit_label": "Send"}
    assert Form.model_validate(data).pages[0].elements[0].visible_if is not None


def test_unknown_keys_rejected() -> None:
    assert "extra_forbidden" in codes(form(fld("a", colour="red")))


def test_bad_id_rejected() -> None:
    assert "string_pattern_mismatch" in codes(form(fld("Full Name")))


def test_duplicate_ids() -> None:
    assert codes(form(fld("a"), fld("a"))) == ["duplicate_id"]


def test_page_and_element_share_id_namespace() -> None:
    assert codes(form(fld("p1"))) == ["duplicate_id"]


def test_reserved_id() -> None:
    assert "reserved_id" in codes(form(fld("submit")))


def test_choice_needs_options() -> None:
    assert "too_short" in codes(form(fld("c", "single_choice", options=[])))


def test_duplicate_option_values() -> None:
    opts = [{"value": "a", "label": "A"}, {"value": "a", "label": "B"}]
    assert "value_error" in codes(form(fld("c", "multi_choice", options=opts)))


def test_repeater_cannot_nest() -> None:
    inner = {"kind": "repeater", "id": "inner", "label": "i", "elements": []}
    outer = {"kind": "repeater", "id": "outer", "label": "o", "elements": [inner]}
    assert codes(form(outer)) == ["repeater_nested"]


def test_section_depth_limit() -> None:
    s3 = {"kind": "section", "id": "s3", "elements": [fld("x")]}
    s2 = {"kind": "section", "id": "s2", "elements": [s3]}
    s1 = {"kind": "section", "id": "s1", "elements": [s2]}
    assert codes(form(s1)) == ["section_too_deep"]
    Form.model_validate(form({**s1, "elements": [{**s2, "elements": [fld("x")]}]}))


def test_signature_not_in_repeater() -> None:
    rep = {
        "kind": "repeater",
        "id": "r",
        "label": "r",
        "elements": [fld("sig", "signature")],
    }
    assert codes(form(rep)) == ["signature_in_repeater"]


def test_condition_value_rules() -> None:
    assert "value_error" in codes(form(fld("a"), fld("b", visibleIf={"field": "a", "op": "eq"})))
    assert "value_error" in codes(
        form(fld("a"), fld("b", visibleIf={"field": "a", "op": "empty", "value": 1}))
    )
    assert "value_error" in codes(
        form(fld("a"), fld("b", visibleIf={"field": "a", "op": "in", "value": "x"}))
    )


def test_unknown_reference() -> None:
    assert codes(form(fld("b", visibleIf={"field": "nope", "op": "empty"}))) == [
        "unknown_reference"
    ]


def test_reference_to_content_or_page() -> None:
    content = {"kind": "content", "id": "c", "contentType": "divider"}
    assert codes(form(content, fld("b", visibleIf={"field": "c", "op": "empty"}))) == [
        "not_value_field"
    ]
    assert codes(form(fld("b", visibleIf={"field": "p1", "op": "empty"}))) == ["not_value_field"]


def test_repeater_scope() -> None:
    rep = {"kind": "repeater", "id": "r", "label": "r", "elements": [fld("rx")]}
    assert codes(form(rep, fld("b", visibleIf={"field": "rx", "op": "empty"}))) == [
        "repeater_scope"
    ]
    assert codes(form(rep, fld("b", visibleIf={"field": "r", "op": "eq", "value": 1}))) == [
        "repeater_op"
    ]
    Form.model_validate(
        form(rep, fld("b", visibleIf={"field": "r", "op": "count_gte", "value": 1}))
    )


def test_count_ops_need_countable_field() -> None:
    assert codes(
        form(fld("a"), fld("b", visibleIf={"field": "a", "op": "count_eq", "value": 1}))
    ) == ["count_op_type"]


def test_goto_rules() -> None:
    data = form(fld("a"))
    data["pages"].append({"id": "p2", "elements": [fld("b")]})
    data["pages"][1]["next"] = [{"if": {"all": []}, "goto": "p1"}]
    assert codes(data) == ["goto_not_forward"]
    data["pages"][1]["next"] = [{"if": {"all": []}, "goto": "p9"}]
    assert codes(data) == ["goto_unknown"]
    data["pages"][1]["next"] = [{"if": {"all": []}, "goto": "submit"}]
    Form.model_validate(data)


def test_page_logic_reads_only_earlier_pages() -> None:
    data = form(fld("a"))
    data["pages"].append({"id": "p2", "elements": [fld("b")]})
    bad = copy.deepcopy(data)
    bad["pages"][0]["visibleIf"] = {"field": "a", "op": "empty"}
    assert codes(bad) == ["page_reference_not_earlier"]
    bad = copy.deepcopy(data)
    bad["pages"][0]["next"] = [{"if": {"field": "b", "op": "empty"}, "goto": "p2"}]
    assert codes(bad) == ["page_reference_not_earlier"]
    ok = copy.deepcopy(data)
    ok["pages"][1]["visibleIf"] = {"field": "a", "op": "empty"}
    ok["pages"][0]["next"] = [{"if": {"field": "a", "op": "empty"}, "goto": "submit"}]
    Form.model_validate(ok)


def test_publish_issues_flag_blank_texts() -> None:
    opts = [{"value": "a", "label": ""}]
    heading = {"kind": "content", "id": "h", "contentType": "heading", "text": " "}
    data = form({**fld("a"), "label": " "}, fld("c", "single_choice", options=opts), heading)
    data["settings"]["title"] = ""
    data["pages"][0]["title"] = ""  # optional texts may be blank
    issues = collect_publish_issues(Form.model_validate(data))
    assert [i.code for i in issues] == ["blank_text"] * 4
    assert [i.target for i in issues] == [
        "form.settings.title",
        "form.pages[0].elements[0].label",
        "form.pages[0].elements[1].options[0].label",
        "form.pages[0].elements[2].text",
    ]
    assert collect_publish_issues(Form.model_validate(EXAMPLE)) == []


def test_json_schema_spec_is_current() -> None:
    assert export_main(["--check"]) == 0, "run: uv run python -m app.schemas.export"
    assert '"title": "JustFormsForm"' in render()
