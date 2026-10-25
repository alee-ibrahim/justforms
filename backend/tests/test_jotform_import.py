"""Jotform importer without a database: HTML/API readers, the type mapping, conditions, the
report, and the submission export conversion (DESIGN 13)."""

from __future__ import annotations

import io
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from openpyxl import Workbook

from app.importers.dom import parse_html
from app.importers.jotform import api_source
from app.importers.jotform.convert import convert
from app.importers.jotform.fetch import FetchError, normalise_url
from app.importers.jotform.html_source import NotAJotform, read_html
from app.importers.jotform.model import JfCondition, JfOption, JfQuestion, JfSource
from app.importers.jotform.submissions import (
    IGNORE,
    TableError,
    convert_row,
    importable_fields,
    parse_date,
    parse_number,
    parse_time,
    read_table,
    suggest_mapping,
)
from app.importers.jotform.text import html_to_markdown, option_values, snake
from app.schemas.form import Form

FIXTURES = Path(__file__).parent / "fixtures" / "jotform"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def elements(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    stack = [e for p in doc["pages"] for e in p["elements"]]
    while stack:
        el = stack.pop()
        out[el["id"]] = el
        stack.extend(el.get("elements", []))
    return out


# -- the anonymised real form ----------------------------------------------------------------


SECTION_TITLES = [
    "BASIC INFORMATION",
    "GOVERNANCE STRUCTURE",
    "MISSION AND OBJECTIVES",
    "AREAS OF INTEREST",
    "DISCLAIMER AND SIGNATURE",
]


@pytest.fixture(scope="module")
def registration() -> Any:
    return convert(read_html(fixture("registration_form.html")))


def test_registration_reads_every_control() -> None:
    src = read_html(fixture("registration_form.html"))
    assert len(src.questions) == 79
    assert Counter(q.type for q in src.questions) == {
        "control_textbox": 35,
        "control_divider": 16,
        "control_collapse": 5,
        "control_text": 5,
        "control_email": 4,
        "control_phone": 4,
        "control_checkbox": 3,
        "control_datetime": 2,
        "control_head": 2,
        "control_fileupload": 1,
        "control_signature": 1,
        "control_button": 1,
    }
    assert src.form_id == "200000000000001"
    assert src.conditions == []
    assert src.cover_image


def test_registration_converts(registration: Any) -> None:
    doc = registration.form
    Form.model_validate(doc)
    assert registration.language == "en"
    assert doc["settings"]["title"] == "Community Network"
    assert doc["settings"]["description"] == "Volunteer Groups Network"
    assert "submitLabel" not in doc["settings"]
    # No page breaks, five collapsible sections: one step (page) per section by default.
    assert registration.collapse_sections == 5 and registration.collapse_as_pages
    assert [p["id"] for p in doc["pages"]] == [f"page_{n}" for n in range(1, 6)]
    assert [p["title"] for p in doc["pages"]] == SECTION_TITLES
    assert not any(e["kind"] == "section" for p in doc["pages"] for e in p["elements"])
    # The heading before the first section joins the first step.
    assert doc["pages"][0]["elements"][0]["id"] == "heading_1"
    assert [e["id"] for e in doc["pages"][4]["elements"]] == ["paragraph_1", "signature", "date"]
    els = elements(doc)
    name = els["group_name"]
    assert name["type"] == "short_text" and name["required"] and name["width"] == "half"
    assert name["description"] == "Full legal name of the organization"
    assert els["acronym"].get("required") is None
    assert els["registration_date"]["type"] == "date"
    assert els["registration_date"]["maxDate"] == "today"
    assert "minDate" not in els["registration_date"]
    assert els["main_phone"]["defaultCountry"] == "GB"
    assert els["main_email"]["type"] == "email"
    assert els["main_email"]["placeholder"] == "email@example.com"
    # An empty label takes the sub-label.
    assert els["aptunit"]["label"] == "Apt Unit" and "description" not in els["aptunit"]
    assert els["group_profile"] == {
        "id": "group_profile",
        "kind": "field",
        "label": "GROUP PROFILE",
        "type": "file",
        "accept": [".pdf"],
        "maxFiles": 1,
        "maxSizeMb": 25,
    }
    areas = els["interest_areas"]
    assert areas["type"] == "multi_choice" and areas["allowOther"] is True
    assert len(areas["options"]) == 14
    assert areas["options"][0] == {"value": "arts_and_culture", "label": "ARTS AND CULTURE"}
    assert "list any other areas" in areas["description"]
    assert len(els["working_groups"]["options"]) == 19
    assert els["signature"]["type"] == "signature"
    assert els["signature"]["description"] == "Group official responsible for the application"
    assert els["heading_4"]["text"] == "SELECTION OF WORKING GROUPS"
    para = els["paragraph_1"]["text"]
    assert para.startswith("I certify that the information provided above is true")
    assert "removal from the network." in para
    assert sum(1 for e in els.values() if e.get("contentType") == "divider") == 16


def test_registration_as_sections() -> None:
    conv = convert(read_html(fixture("registration_form.html")), collapse_as_pages=False)
    doc = conv.form
    assert conv.collapse_sections == 5 and not conv.collapse_as_pages
    assert len(doc["pages"]) == 1
    sections = [e for e in doc["pages"][0]["elements"] if e["kind"] == "section"]
    assert [s["title"] for s in sections] == SECTION_TITLES
    report = conv.report.as_json()
    collapse = [i for i in report["items"] if i["jotformType"] == "control_collapse"]
    assert {i["justformsType"] for i in collapse} == {"section"}
    assert any("shown open" in n for n in report["notes"])


def test_steps_keep_the_same_question_ids(registration: Any) -> None:
    sections = convert(read_html(fixture("registration_form.html")), collapse_as_pages=False)
    as_steps = {k for k, v in elements(registration.form).items() if v["kind"] != "section"}
    as_sections = {k for k, v in elements(sections.form).items() if v["kind"] != "section"}
    assert as_steps == as_sections


def test_registration_report(registration: Any) -> None:
    report = registration.report.as_json()
    assert report["counts"] == {"imported": 74, "changed": 5, "skipped": 0}
    assert len(report["items"]) == 79
    collapse = [i for i in report["items"] if i["jotformType"] == "control_collapse"]
    assert [i["justformsType"] for i in collapse] == ["page"] * 5
    assert [i["elementId"] for i in collapse] == [f"page_{n}" for n in range(1, 6)]
    assert "step" in collapse[0]["notes"][0]
    assert any("5 collapsible sections became a step" in n for n in report["notes"])
    assert report["conditions"] == []
    assert "no conditions" in report["conditionsNote"]
    assert any("Cover image" in d for d in report["dropped"])
    title = report["items"][0]
    assert title["jotformType"] == "control_head" and title["justformsType"] == "form title"


def _q(qid: str, type_: str, label: str = "", **kw: Any) -> JfQuestion:
    return JfQuestion(qid=qid, type=type_, label=label, name=snake(label) if label else "", **kw)


def _mixed(intro_field: bool = True) -> JfSource:
    """Page breaks and collapsible sections together, with a page skip and a section rule."""
    questions = [
        _q("1", "control_head", text="Mixed"),
        *([_q("2", "control_textbox", "Intro")] if intro_field else []),
        _q("3", "control_collapse", text="First section"),
        _q("4", "control_radio", "Skip ahead", options=[JfOption("Yes"), JfOption("No")]),
        _q("5", "control_pagebreak"),
        _q("6", "control_collapse", text="Second section"),
        _q("7", "control_textbox", "Second"),
        _q("8", "control_pagebreak"),
        _q("9", "control_textbox", "Last"),
    ]
    skip = {
        "type": "page",
        "terms": [{"field": "4", "operator": "equals", "value": "Yes"}],
        "action": [{"skipTo": "page-3"}],
    }
    show = {
        "type": "field",
        "terms": [{"field": "4", "operator": "equals", "value": "No"}],
        "action": [{"visibility": "Show", "field": "6"}],
    }
    return JfSource(
        title="Mixed", questions=questions, conditions=[JfCondition(skip), JfCondition(show)]
    )


def test_page_breaks_win_by_default() -> None:
    conv = convert(_mixed())
    assert conv.collapse_sections == 2 and not conv.collapse_as_pages
    doc = conv.form
    assert len(doc["pages"]) == 3
    assert [e["kind"] for e in doc["pages"][1]["elements"]] == ["section"]
    assert doc["pages"][0]["next"][0]["goto"] == "page_3"
    assert doc["pages"][1]["elements"][0]["visibleIf"]["field"] == "skip_ahead"


def test_collapses_and_page_breaks_as_steps() -> None:
    conv = convert(_mixed(), collapse_as_pages=True)
    doc = conv.form
    Form.model_validate(doc)
    # The intro question keeps a page; each section and each Jotform page start one.
    assert [p.get("title") for p in doc["pages"]] == [None, "First section", "Second section", None]
    assert [e["id"] for e in doc["pages"][0]["elements"]] == ["intro"]
    # "Skip to Jotform page 3" lands on the page that page became, from the question's page.
    assert doc["pages"][1]["next"] == [
        {"if": {"field": "skip_ahead", "op": "eq", "value": True}, "goto": "page_4"}
    ]
    # A rule on a section now shows or hides its page.
    assert doc["pages"][2]["visibleIf"] == {"field": "skip_ahead", "op": "eq", "value": False}
    assert [c.status for c in conv.report.conditions] == ["imported", "imported"]


def test_heading_only_intro_joins_the_first_step() -> None:
    doc = convert(_mixed(intro_field=False), collapse_as_pages=True).form
    assert doc["pages"][0]["title"] == "First section"
    assert len(doc["pages"]) == 3


# -- the other control types ---------------------------------------------------------------


@pytest.fixture(scope="module")
def controls() -> Any:
    return convert(read_html(fixture("all_controls.html")), max_upload_mb=25)


def test_controls_pages_and_parts(controls: Any) -> None:
    doc = controls.form
    assert [p["id"] for p in doc["pages"]] == ["page_1", "page_2"]
    assert doc["pages"][1]["title"] == "Details"
    assert doc["pages"][1]["description"] == "A few more questions."
    assert doc["settings"]["submitLabel"] == "Sign me up"
    assert controls.captcha is True
    els = elements(doc)
    name = els["your_name"]
    assert name["kind"] == "section" and name["title"] == "Your name"
    assert [(c["id"], c["label"], c.get("required")) for c in name["elements"]] == [
        ("your_name_first", "First Name", True),
        ("your_name_last", "Last Name", True),
    ]
    address = els["address"]
    assert [c["id"] for c in address["elements"]] == [
        "address_addr_line1",
        "address_city",
        "address_postal",
        "address_country",
    ]
    country = els["address_country"]
    assert country["type"] == "single_choice" and country["display"] == "dropdown"
    assert [o["label"] for o in country["options"]] == ["Iceland", "Norway"]


def test_controls_field_types(controls: Any) -> None:
    els = elements(controls.form)
    notes = els["anything_else"]
    assert notes["type"] == "long_text" and notes["maxLength"] == 500 and notes["rows"] == 6
    assert notes["placeholder"] == "Optional notes"
    assert notes["description"] == "Dietary needs, access needs and so on."
    assert els["work_email"]["type"] == "email"
    assert els["session"]["display"] == "dropdown" and els["session"]["required"]
    assert [o["value"] for o in els["session"]["options"]] == [
        "morning_talk",
        "workshop",
        "evening_social",
    ]
    guests = els["guests"]
    assert (guests["min"], guests["max"], guests["step"], guests["integer"]) == (0, 5, 1, True)
    assert guests["width"] == "half"
    assert (els["ticket_code"]["min"], els["ticket_code"]["max"]) == (1000, 9999)
    arrival = els["arrival"]
    assert (arrival["minDate"], arrival["maxDate"]) == ("today", "2027-12-31")
    assert els["arrival_time"]["type"] == "time" and els["arrival_time"]["required"]
    assert els["arrival_time"]["label"] == "Arrival (time)"
    assert els["leaving_at"]["type"] == "time"
    assert els["staying_for"]["type"] == "yes_no"
    assert els["main_course"]["allowOther"] is True
    assert [o["label"] for o in els["main_course"]["options"]] == ["Fish", "Vegetable curry"]
    assert els["workshop_materials"]["maxSelected"] == 2
    assert els["rate_the_last_event"] == {
        "id": "rate_the_last_event",
        "kind": "field",
        "label": "Rate the last event",
        "type": "rating",
        "max": 5,
    }
    assert els["how_likely"]["max"] == 10
    photos = els["photos"]
    assert photos["accept"] == [".jpg", ".jpeg", ".png"]
    assert (photos["maxFiles"], photos["maxSizeMb"]) == (3, 25)
    assert els["reference"]["type"] == "hidden"
    assert els["paragraph_1"]["text"] == (
        "Read the **event rules** at [example.org/rules](https://example.org/rules).\n\n"
        "- Arrive early\n- Bring _your ticket_"
    )


def test_controls_report_and_conditions(controls: Any) -> None:
    report = controls.report.as_json()
    by_qid = {i["qid"]: i for i in report["items"]}
    assert by_qid["25"]["status"] == "skipped" and "Matrix" in by_qid["25"]["notes"][0]
    assert by_qid["26"]["status"] == "skipped"
    assert by_qid["14"]["status"] == "changed"  # confirm email dropped
    assert by_qid["28"]["status"] == "changed"  # size limit lowered
    assert any("started at 0" in n for n in by_qid["24"]["notes"])
    statuses = [(c["status"], c["reason"][:30]) for c in report["conditions"]]
    assert [s for s, _ in statuses] == [
        "imported",
        "imported",
        "imported",
        "not_imported",
        "not_imported",
    ]
    assert "Calculations" in report["conditions"][3]["reason"]
    assert "startsWith" in report["conditions"][4]["reason"]
    els = elements(controls.form)
    assert els["main_course"]["visibleIf"] == {"field": "staying_for", "op": "eq", "value": True}
    assert els["workshop_materials"]["requiredIf"] == {
        "all": [
            {"field": "session", "op": "eq", "value": "workshop"},
            {"field": "guests", "op": "gt", "value": 2.0},
        ]
    }
    assert controls.form["pages"][1]["next"] == [
        {"if": {"field": "staying_for", "op": "eq", "value": False}, "goto": "submit"}
    ]


def test_dhivehi_form_is_detected() -> None:
    conv = convert(read_html(fixture("dhivehi_form.html")))
    assert conv.language == "dv" and conv.detected_language == "dv"
    doc = conv.form
    assert doc["settings"]["language"] == "dv"
    assert "submitLabel" not in doc["settings"]  # the default "submit" word
    # Thaana labels give type-based ids.
    assert [e["id"] for e in doc["pages"][0]["elements"]] == [
        "short_text_1",
        "short_text_2",
        "phone_1",
        "yes_no_1",
        "multi_choice_1",
    ]
    assert [o["value"] for o in doc["pages"][0]["elements"][4]["options"]] == [
        "option_1",
        "option_2",
    ]
    forced = convert(read_html(fixture("dhivehi_form.html")), language="en")
    assert forced.form["settings"]["language"] == "en"
    assert forced.report.notes and "Dhivehi" in forced.report.notes[0]


def test_embed_code_is_not_the_source() -> None:
    embed = (
        '<iframe id="JotFormIFrame-200000000000009" '
        'src="https://form.jotform.com/200000000000009"></iframe>'
    )
    with pytest.raises(NotAJotform) as info:
        read_html(embed)
    assert info.value.form_url == "https://form.jotform.com/200000000000009"
    with pytest.raises(NotAJotform) as nothing:
        read_html("<p>hello</p>")
    assert nothing.value.form_url is None


def test_text_helpers() -> None:
    assert snake("csoName") == "cso_name"
    assert snake("Full Name (legal)") == "full_name_legal"
    assert snake("3 things") == "q_3_things"
    assert snake("ފުރިހަމަ ނަން") == ""
    assert option_values(["Yes", "yes", "ނޫން"]) == ["yes", "yes_2", "option_3"]
    assert html_to_markdown("<b>Bold</b> and <a href='javascript:x'>bad</a><br>next") == (
        "**Bold** and bad\nnext"
    )
    root = parse_html("<div><script>var a = '<li>';</script><p>Hi</p></div>")
    assert root.text() == "Hi"


def test_unclosed_markup_is_tolerated() -> None:
    root = parse_html("<ul><li>one<li>two</ul><p>after")
    # No implied end tags: the second item nests in the first, nothing is lost.
    assert [n.text() for n in root.by_tag("li")] == ["onetwo", "two"]
    assert root.text() == "onetwoafter"


# -- API path ------------------------------------------------------------------------------


def test_api_questions_map_like_html() -> None:
    questions = {
        "1": {"qid": "1", "type": "control_head", "text": "Sign-up", "order": "1"},
        "2": {
            "qid": "2",
            "type": "control_textbox",
            "text": "Name",
            "name": "name",
            "order": "2",
            "required": "Yes",
            "validation": "None",
            "maxsize": "80",
        },
        "3": {
            "qid": "3",
            "type": "control_radio",
            "text": "Colour",
            "name": "colour",
            "order": "3",
            "options": "Red|Blue",
            "allowOther": "Yes",
        },
        "4": {"qid": "4", "type": "control_matrix", "text": "Grid", "order": "4"},
    }
    properties = {
        "conditions": [
            {
                "type": "field",
                "link": "Any",
                "terms": '[{"field":"3","operator":"equals","value":"Red"}]',
                "action": '[{"visibility":"Show","field":"2"}]',
            }
        ]
    }
    src = api_source.source_from_api({"id": "55", "title": "Sign-up"}, questions, properties)
    conv = convert(src, source_kind="api")
    els = elements(conv.form)
    assert els["name"]["required"] and els["name"]["maxLength"] == 80
    assert els["colour"]["allowOther"] is True
    assert els["name"]["visibleIf"] == {"field": "colour", "op": "eq", "value": "red"}
    assert conv.report.counts()["skipped"] == 1


async def test_api_client_sends_key_in_header_only() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/user/forms":
            return httpx.Response(
                200,
                json={"content": [{"id": "1", "title": "A", "count": "3", "status": "ENABLED"}]},
            )
        return httpx.Response(401, json={"message": "bad"})

    transport = httpx.MockTransport(handler)
    forms = await api_source.list_forms("eu", "k" * 32, transport=transport)
    assert forms == [{"id": "1", "title": "A", "count": 3, "status": "ENABLED", "updatedAt": None}]
    assert seen[0].url.host == "eu-api.jotform.com"
    assert seen[0].headers["APIKEY"] == "k" * 32
    assert "k" * 32 not in str(seen[0].url)
    with pytest.raises(api_source.JotformApiError) as err:
        await api_source.read_form("us", "k" * 32, "123", transport=transport)
    assert err.value.code == "bad_key"


# -- fetch-by-URL guard --------------------------------------------------------------------


def test_url_allowlist() -> None:
    assert normalise_url("200000000000001") == "https://form.jotform.com/200000000000001"
    assert normalise_url("form.jotform.com/200000000000001") == (
        "https://form.jotform.com/200000000000001"
    )
    for bad in (
        "http://form.jotform.com/1",
        "https://example.org/form",
        "https://form.jotform.com.example.org/1",
        "https://user:pw@form.jotform.com/1",
        "https://form.jotform.com:8443/1",
        "file:///etc/passwd",
    ):
        with pytest.raises(FetchError):
            normalise_url(bad)


# -- submission exports ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def registration_form(registration: Any) -> Form:
    return Form.model_validate(registration.form)


def test_csv_export_mapping(registration_form: Form) -> None:
    data = (FIXTURES / "registration_submissions.csv").read_bytes()
    table = read_table(data, "export.csv")
    assert len(table.headers) == 53 and len(table.rows) == 4
    mapping = suggest_mapping(table.headers, registration_form)
    assert mapping[0] == "meta:submitted_at"
    assert mapping[-2:] == ["meta:external_id", "meta:ip"]
    # Repeated labels map in order.
    phones = [m for h, m in zip(table.headers, mapping, strict=True) if h == "Phone"]
    assert phones == [
        "field:main_phone",
        "field:key_person1_phone",
        "field:key_person2_phone",
        "field:key_person3_phone",
    ]
    assert IGNORE not in mapping
    fields = {f.id: f for f in importable_fields(registration_form)}
    tz = ZoneInfo("UTC")
    first = convert_row(table.rows[0], mapping, fields, tz)
    assert first.problems == []
    assert first.external_id == "6100000000000000001" and first.ip == "192.0.2.10"
    assert first.submitted_at is not None and first.submitted_at.isoformat().startswith(
        "2025-03-14T09:12"
    )
    assert first.data["registration_date"] == "2019-05-20"
    assert first.data["main_phone"] == "+447771234"
    assert first.data["interest_areas"] == ["youth", "sports"]
    assert first.data["working_groups"] == ["working_group_1", "working_group_3"]
    assert first.data["date"] == "2025-03-14"
    assert "group_profile" not in first.data and "signature" not in first.data
    assert first.links["group_profile"][0].endswith("/profile.pdf")
    assert first.links["signature"][0].endswith("/signature.png")
    second = convert_row(table.rows[1], mapping, fields, tz)
    assert [(table.headers[c], code) for c, code, _ in second.problems] == [("Email", "email")]
    assert second.data["interest_areas"] == ["gardening", "Running a seed library"]
    last = convert_row(table.rows[3], mapping, fields, tz)
    assert last.data["registration_date"] == "2020-02-13"  # 13/02 can only be day-first
    assert last.data["activities"] == ["newsletters", "UNKNOWN ACTIVITY"]
    assert last.submitted_at is not None and last.submitted_at.date() == date(2025, 3, 16)


def test_xlsx_export_reads_the_same(registration_form: Form) -> None:
    csv_table = read_table((FIXTURES / "registration_submissions.csv").read_bytes(), "a.csv")
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(csv_table.headers)
    for row in csv_table.rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    table = read_table(buf.getvalue(), "export.xlsx")
    assert table.headers == csv_table.headers
    assert [r[1] for r in table.rows] == [r[1] for r in csv_table.rows]


def test_table_errors() -> None:
    with pytest.raises(TableError):
        read_table(b"", "a.csv")
    with pytest.raises(TableError):
        read_table(b"PK\x03\x04 not really a workbook", "a.xlsx")
    semicolons = read_table("Name;Age\nAli;30\n".encode("cp1252"), "a.csv")
    assert semicolons.headers == ["Name", "Age"] and semicolons.rows == [["Ali", "30"]]


@pytest.mark.parametrize(
    ("text", "order", "expected"),
    [
        ("2026-10-24", "auto", date(2026, 10, 24)),
        ("2026/10/24 10:15", "auto", date(2026, 10, 24)),
        ("10/24/2026", "auto", date(2026, 10, 24)),
        ("03/04/2026", "auto", date(2026, 3, 4)),
        ("03/04/2026", "dmy", date(2026, 4, 3)),
        ("24-10-2026", "auto", date(2026, 10, 24)),
        ("Oct 24, 2026", "auto", date(2026, 10, 24)),
        ("24 October 2026", "auto", date(2026, 10, 24)),
        ("2026-10-24T08:00:00", "auto", date(2026, 10, 24)),
        ("31/02/2026", "auto", None),
        ("soon", "auto", None),
    ],
)
def test_parse_date(text: str, order: str, expected: date | None) -> None:
    assert parse_date(text, order) == expected


def test_parse_number_and_time() -> None:
    assert parse_number("1,234.5") == 1234.5
    assert parse_number("1.234,5") == 1234.5
    assert parse_number("12,5") == 12.5
    assert parse_number("7") == 7
    assert parse_number("x") is None
    assert parse_time("2:05 PM") == "14:05"
    assert parse_time("12:30 AM") == "00:30"
    assert parse_time("09:15") == "09:15"
    assert parse_time("25:00") is None
