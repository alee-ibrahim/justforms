"""Forms that mix English and Dhivehi (schemaVersion 2): every text takes its own direction,
and alignment follows ``align`` on the element, then ``settings.align``, then the text."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pypdfium2 as pdfium

from app.answers import answer_text
from app.notifications import emails
from app.pdf.render import PdfInput, render_pdf
from app.schemas.form import Form
from tests.helpers import field

MIXED = "Name / ނަން"


def _form(*elements: dict[str, Any], title: str = "Application", **settings: Any) -> Form:
    return Form.model_validate(
        {
            "schemaVersion": "2",
            "settings": {"title": title, **settings},
            "pages": [{"id": "p1", "elements": list(elements)}],
        }
    )


def _mixed_form(**settings: Any) -> Form:
    return _form(
        {"kind": "content", "id": "h", "contentType": "heading", "text": "ބައި 1 / Part 1"},
        field("name", label=MIXED, align="right"),
        field("dv_name", label="ނަން"),
        field("email", "email", label="Email", align="center"),
        {
            "kind": "field",
            "id": "pick",
            "type": "multi_choice",
            "label": "ކުލަ",
            "options": [{"value": "a", "label": "ރަތް"}, {"value": "b", "label": "ނޫ"}],
        },
        title="Application / ހުށަހަޅާ ފޯމު",
        **settings,
    )


DATA = {
    "name": "Aminath",
    "dv_name": "އާމިނަތު",
    "email": "a@example.org",
    "pick": ["a", "b"],
}


def _pdf(form: Form) -> bytes:
    return render_pdf(
        PdfInput(
            org_name="Example Office",
            form_title=form.settings.title,
            form=form,
            version=1,
            schema_hash="x",
            submission_id="00000000-0000-0000-0000-000000000000",
            seq=7,
            submitted_at=datetime(2026, 11, 1, tzinfo=UTC),
            data=DATA,
            content_hash="y",
            chain_head=None,
            tz=ZoneInfo("UTC"),
            verify_url="http://testserver/v/token",
        )
    )


def _char_x(page: Any, text: str, needle: str) -> float:
    """Left edge (pt) of the first character of ``needle`` on the page."""
    tp = page.get_textpage()
    try:
        full = tp.get_text_range()
        i = full.find(needle)
        assert i >= 0, (needle, full)
        return float(tp.get_charbox(i)[0])
    finally:
        tp.close()


def test_mixed_form_pdf_renders_with_thaana_face_and_per_field_alignment() -> None:
    pdf = _pdf(_mixed_form())
    assert pdf.startswith(b"%PDF")
    assert b"NotoSansThaana" in pdf and b"Inter" in pdf
    doc = pdfium.PdfDocument(pdf)
    page = doc[0]
    width = page.get_width()
    tp = page.get_textpage()
    text = tp.get_text_range()
    tp.close()
    # Both scripts of the mixed label are there, English first.
    assert "Name" in text and "Aminath" in text and "a@example.org" in text
    # "Name / ..." is aligned right (its own align); "Email" is centred.
    assert _char_x(page, text, "Aminath") > width / 2
    email_x = _char_x(page, text, "a@example.org")
    assert width * 0.3 < email_x < width / 2
    # The sheet chrome follows the title (English first: left to right).
    assert _char_x(page, text, "Reference") < width / 4
    doc.close()


def test_form_default_alignment_applies_to_every_text() -> None:
    pdf = _pdf(_mixed_form(align="center"))
    doc = pdfium.PdfDocument(pdf)
    page = doc[0]
    width = page.get_width()
    tp = page.get_textpage()
    text = tp.get_text_range()
    tp.close()
    # The name keeps its own "right"; the email (centre) is centred either way.
    assert _char_x(page, text, "Aminath") > width / 2
    assert width * 0.3 < _char_x(page, text, "a@example.org") < width / 2
    doc.close()


def test_dhivehi_title_makes_a_right_to_left_sheet() -> None:
    form = _form(field("name", label="Name"), title="ހުށަހަޅާ ފޯމު")
    pdf = _pdf(form)
    doc = pdfium.PdfDocument(pdf)
    page = doc[0]
    tp = page.get_textpage()
    text = tp.get_text_range()
    tp.close()
    # The English reference line sits at the right edge of a right-to-left sheet; the English
    # label of the question stays at the left (its own direction).
    assert _char_x(page, text, "Reference") > page.get_width() / 2
    assert _char_x(page, text, "Name") < page.get_width() / 4
    doc.close()


def test_rtl_option_lists_take_the_arabic_comma() -> None:
    form = _mixed_form()
    pick = form.pages[0].elements[4]
    assert answer_text(pick, ["a", "b"]) == "ރަތް، ނޫ"  # type: ignore[arg-type]
    en = (
        _form(
            {
                "kind": "field",
                "id": "pick",
                "type": "multi_choice",
                "label": "Colours",
                "options": [{"value": "a", "label": "Red"}, {"value": "b", "label": "Blue"}],
            }
        )
        .pages[0]
        .elements[0]
    )
    assert answer_text(en, ["a", "b"]) == "Red, Blue"  # type: ignore[arg-type]
    assert answer_text(en, ["a", "b"], list_sep="; ") == "Red; Blue"  # type: ignore[arg-type]


def _receipt(form: Form) -> str:
    msg = emails.receipt_message(
        org_name="Example Office",
        form=form,
        title=form.settings.title,
        reference="#0007",
        submitted=datetime(2026, 11, 1, tzinfo=UTC),
        tz=ZoneInfo("UTC"),
        answers=emails.answers_for_email(form, DATA),
        pdf=None,
    )
    return msg.html or ""


def _div(html: str, inner: str) -> str:
    """The opening tag of the block whose content starts with ``inner``."""
    m = re.search(r"<(?:div|p|h1)([^>]*)>" + re.escape(inner), html)
    assert m, inner
    return m.group(1)


def test_email_gives_every_text_its_own_direction_and_alignment() -> None:
    form = _mixed_form(successMessage="ޝުކުރިއްޔާ")
    html = _receipt(form)
    # The mixed label reads left to right (English first) but is aligned right (its align).
    label = _div(html, "Name / ")
    assert 'dir="ltr"' in label and 'lang="en"' in label and 'align="right"' in label
    assert "Noto Sans Thaana" in label
    # Its Latin answer: left to right, aligned with its question.
    answer = _div(html, "Aminath")
    assert 'dir="ltr"' in answer and 'align="right"' in answer
    # A Thaana label and answer: right to left, Thaana face and scale.
    dv_label = _div(html, "ނަން<")
    assert 'dir="rtl"' in dv_label and 'lang="dv"' in dv_label and 'align="right"' in dv_label
    assert "font-size:16px" in dv_label
    dv_answer = _div(html, "އާމިނަތު")
    assert 'dir="rtl"' in dv_answer and "font-size:18px" in dv_answer
    # Centred English question.
    assert 'align="center"' in _div(html, "Email")
    # The title (English first) and the Dhivehi success message each take their own direction.
    title = _div(html, "Application / ")
    assert 'dir="ltr"' in title and 'align="left"' in title
    success = _div(html, "ޝުކުރިއްޔާ")
    assert 'dir="rtl"' in success and 'align="right"' in success
    # The email itself stays English, left to right.
    assert '<html lang="en">' in html


def test_email_title_alignment_and_isolation() -> None:
    form = _mixed_form(titleAlign="center")
    assert 'align="center"' in _div(_receipt(form), "Application / ")
    dv = _form(field("a", label="A"), title="ފޯމު")
    msg = emails.receipt_message(
        org_name="Example Office",
        form=dv,
        title="ފޯމު",
        reference="#0007",
        submitted=datetime(2026, 11, 1, tzinfo=UTC),
        tz=ZoneInfo("UTC"),
        answers=[],
        pdf=None,
    )
    # A right-to-left title inside an English subject is isolated; an English one is not.
    assert "⁨ފޯމު⁩ (#0007)" in msg.subject
    code = emails.code_message(org_name="", title="Mixed / ފޯމު", code="123456", minutes=10)
    assert "⁨" not in code.subject


# An English paragraph followed by Dhivehi ones: direction is resolved per line.
PARAGRAPHS = "Please read the notes below.\n\nމި ފޯމު ފުރިހަމަ ކުރައްވާ.\nސުވާލުތަކަށް ޖަވާބު ދެއްވާ."


def _long_form(**settings: Any) -> Form:
    return _form(
        {"kind": "field", "id": "notes", "type": "long_text", "label": "Notes"},
        successMessage=PARAGRAPHS,
        **settings,
    )


def _long_receipt(form: Form) -> str:
    msg = emails.receipt_message(
        org_name="Example Office",
        form=form,
        title=form.settings.title,
        reference="#0007",
        submitted=datetime(2026, 11, 1, tzinfo=UTC),
        tz=ZoneInfo("UTC"),
        answers=emails.answers_for_email(form, {"notes": PARAGRAPHS}),
        pdf=None,
    )
    return msg.html or ""


def test_email_multi_paragraph_text_takes_direction_per_line() -> None:
    html = _long_receipt(_long_form())
    english = re.findall(r"<div([^>]*)>Please read", html)
    dhivehi = re.findall(r"<div([^>]*)>ސުވާލުތަކަށް", html)
    # The answer and the success message: each paragraph in its own direction and side.
    assert len(english) == 2 and len(dhivehi) == 2
    for tag in english:
        assert 'dir="ltr"' in tag and 'lang="en"' in tag and 'align="left"' in tag
    for tag in dhivehi:
        assert 'dir="rtl"' in tag and 'lang="dv"' in tag and 'align="right"' in tag
        assert "Noto Sans Thaana" in tag
    # An explicit alignment applies to every paragraph.
    centred = _long_receipt(_long_form(align="center"))
    for tag in re.findall(r"<div([^>]*)>(?:Please read|ސުވާލުތަކަށް)", centred):
        assert 'align="center"' in tag


def test_email_custom_message_takes_direction_per_line() -> None:
    form = _long_form()
    msg = emails.receipt_message(
        org_name="Example Office",
        form=form,
        title=form.settings.title,
        reference="#0007",
        submitted=datetime(2026, 11, 1, tzinfo=UTC),
        tz=ZoneInfo("UTC"),
        answers=[],
        pdf=None,
        wording=emails.Wording(message=PARAGRAPHS),
    )
    html = msg.html or ""
    assert 'dir="rtl"' in _div(html, "ސުވާލުތަކަށް")
    assert 'dir="ltr"' in _div(html, "Please read")


def test_pdf_multi_paragraph_answer_takes_direction_per_line() -> None:
    form = _long_form()
    pdf = render_pdf(
        PdfInput(
            org_name="Example Office",
            form_title=form.settings.title,
            form=form,
            version=1,
            schema_hash="x",
            submission_id="00000000-0000-0000-0000-000000000000",
            seq=7,
            submitted_at=datetime(2026, 11, 1, tzinfo=UTC),
            data={"notes": PARAGRAPHS},
            content_hash="y",
            chain_head=None,
            tz=ZoneInfo("UTC"),
            verify_url="http://testserver/v/token",
        )
    )
    doc = pdfium.PdfDocument(pdf)
    page = doc[0]
    width = page.get_width()
    tp = page.get_textpage()
    text = tp.get_text_range()
    tp.close()
    # The English paragraph starts at the left margin, the Dhivehi ones end at the right.
    assert _char_x(page, text, "Please read") < width / 4
    tp = page.get_textpage()
    try:
        boxes = [tp.get_charbox(i) for i in range(tp.count_chars())]
        chars = tp.get_text_range()
    finally:
        tp.close()
    thaana = [b for c, b in zip(chars, boxes, strict=False) if "\u0780" <= c <= "\u07bf"]
    assert thaana and max(b[2] for b in thaana) > width * 0.85
    doc.close()
