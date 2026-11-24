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
        title="Application form / ހުށަހަޅާ ފޯމު",
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
    # The title (English first) takes its own direction; with auto alignment the bilingual
    # title is one row, English at the left and Dhivehi at the right.
    title = _div(html, '<table role="presentation" width="100%"')
    assert 'dir="ltr"' in title and 'align="left"' in title
    assert re.search(r'<td lang="en" dir="ltr" align="left"[^>]*>Application form</td>', html)
    assert re.search(r'<td lang="dv" dir="rtl" align="right"[^>]*>', html)
    # The Dhivehi success message takes its own direction.
    success = _div(html, "ޝުކުރިއްޔާ")
    assert 'dir="rtl"' in success and 'align="right"' in success
    # The email itself stays English, left to right.
    assert '<html lang="en">' in html


def test_email_title_alignment_and_isolation() -> None:
    form = _mixed_form(titleAlign="center")
    assert 'align="center"' in _div(_receipt(form), "Application form / ")
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
    assert thaana and max(b[1] for b in thaana) > width * 0.85
    doc.close()


def test_email_isolates_the_other_script_and_follows_the_dominant_one() -> None:
    form = _form(
        {"kind": "field", "id": "q", "type": "short_text", "label": "PPY ގެ ބައިވެރިން ކޮބާ؟"},
        title="ބައިވެރިވުމަށް (PPY) ފޯމު ފުރުއްވާ.",
    )
    msg = emails.receipt_message(
        org_name="Example Office",
        form=form,
        title=form.settings.title,
        reference="#0007",
        submitted=datetime(2026, 11, 1, tzinfo=UTC),
        tz=ZoneInfo("UTC"),
        answers=emails.answers_for_email(form, {"q": "2026 ވަނަ އަހަރު."}),
        pdf=None,
    )
    html = msg.html or ""
    # Dhivehi-dominant title and label, though one starts with a Latin acronym: right to left,
    # the acronym isolated so the brackets and question mark stay put.
    assert 'dir="rtl"' in _div(html, "ބައިވެރިވުމަށް <bdi")
    # The bracket pair belongs to the run it encloses.
    assert 'ބައިވެރިވުމަށް <bdi dir="ltr" lang="en">(PPY)</bdi> ފޯމު' in html
    label = re.search(r'<div([^>]*)><bdi dir="ltr" lang="en">PPY</bdi> ގެ', html)
    assert label and 'dir="rtl"' in label.group(1) and 'align="right"' in label.group(1)
    assert 'dir="rtl"' in _div(html, "2026 ވަނަ")


def test_email_justify_follows_each_paragraph_direction() -> None:
    form = _form(
        {"kind": "field", "id": "notes", "type": "long_text", "label": "Notes", "align": "justify"},
    )
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
    html = msg.html or ""
    english = _div(html, "Please read")
    dhivehi = _div(html, "ސުވާލުތަކަށް")
    assert "text-align:justify;text-align-last:left" in english and 'align="left"' in english
    assert "text-align:justify;text-align-last:right" in dhivehi and 'align="right"' in dhivehi
    # The label is one line: it stays at its start edge.
    assert 'align="left"' in _div(html, "Notes")


def test_pdf_justify_ends_each_paragraph_at_its_start_edge() -> None:
    long_en = "The community grant supports small projects that improve public spaces " * 3
    long_dv = "މި ގްރާންޓް ދެވެނީ އާންމު ތަންތަން ރީތިކުރުމަށާއި ޒުވާނުންނަށް ހުނަރު ދަސްކޮށްދިނުމަށް " * 3
    form = _form(
        {"kind": "field", "id": "notes", "type": "long_text", "label": "Notes", "align": "justify"},
    )
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
            data={"notes": f"{long_en}end.\n{long_dv}ނިމުނީ."},
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
    try:
        boxes = [tp.get_charbox(i) for i in range(tp.count_chars())]
        chars = tp.get_text_range()
    finally:
        tp.close()
    thaana = [b for c, b in zip(chars, boxes, strict=False) if "\u0780" <= c <= "\u07bf"]
    # Char boxes are (left, right, bottom, top). Justified Dhivehi lines reach both margins;
    # the last (lowest) line is not stretched and ends at the right margin.
    rows: dict[int, list[Any]] = {}
    for b in thaana:
        rows.setdefault(round(b[3]), []).append(b)
    tops = sorted(rows, reverse=True)
    assert len(tops) >= 2
    first, last = rows[tops[0]], rows[tops[-1]]
    assert min(b[0] for b in first) < width * 0.2 and max(b[1] for b in first) > width * 0.8
    assert max(b[1] for b in last) > width * 0.8
    assert min(b[0] for b in last) > min(b[0] for b in first) + 20
    doc.close()


# Bilingual one-line texts from a public form: English part, Dhivehi part.
PROGRAM = "Which program did you participate in? ބައިވެރިވި ޕްރޮގްރާމަކީ:"
PPY = "ޕްރެކްޓިސް ޕާލިމެންޓް ފޮރ ޔޫތު (ޕީ.ޕީ.ވައި) (Practice Parliament for Youth (PPY))"


def _split_form(**settings: Any) -> Form:
    return _form(
        field("full_name", label="Full name: ފުރިހަމަ ނަން"),
        field("year", label="Year of participation: ބައިވެރިވި އަހަރު"),
        {
            "kind": "field",
            "id": "program",
            "type": "single_choice",
            "label": PROGRAM,
            "options": [{"value": "ppy", "label": PPY}],
        },
        title="Application form / ހުށަހަޅާ ފޯމު",
        **settings,
    )


def _line_chars(page: Any, needle: str) -> tuple[float, list[tuple[str, float]]]:
    """x of ``needle`` and every character on its line with its x (pt)."""
    tp = page.get_textpage()
    try:
        full = tp.get_text_range()
        i = full.find(needle)
        assert i >= 0, (needle, full)
        left, bottom, _right, top = tp.get_charbox(i)
        chars = []
        for j, ch in enumerate(full):
            if ch.isspace():
                continue
            _l, b, _r, t = tp.get_charbox(j)
            if b < top and t > bottom:
                chars.append((ch, float(_l)))
        return float(left), chars
    finally:
        tp.close()


def _thaana_xs_on_line(page: Any, needle: str) -> tuple[float, list[float]]:
    """x of ``needle`` and the x of every Thaana character on its line (pt)."""
    x, chars = _line_chars(page, needle)
    return x, [cx for ch, cx in chars if "\u0780" <= ch <= "\u07bf"]


def _split_pdf(form: Form) -> bytes:
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
            data={"full_name": "Aminath", "year": "2024", "program": "ppy"},
            content_hash="y",
            chain_head=None,
            tz=ZoneInfo("UTC"),
            verify_url="http://testserver/v/token",
        )
    )


def test_pdf_splits_bilingual_texts_english_left_dhivehi_right() -> None:
    doc = pdfium.PdfDocument(_split_pdf(_split_form()))
    page = doc[0]
    width = page.get_width()
    for needle in ("Application", "Full", "Year", "Which"):
        x, thaana = _thaana_xs_on_line(page, needle)
        assert x < width / 4, needle
        assert thaana and min(thaana) > width / 2, needle
    # The option: Dhivehi at the right, the English part at the left with both its bracket
    # pairs, ending in its two closing brackets.
    x, thaana = _thaana_xs_on_line(page, "Practice")
    assert x < width / 4 and thaana and min(thaana) > width / 2
    _x, chars = _line_chars(page, "Practice")
    english = sorted((cx, ch) for ch, cx in chars if cx < width / 2)
    # (Text extraction may map a mirrored bracket glyph to either bracket.)
    assert len([ch for _cx, ch in english if ch in "()"]) == 4
    assert english[0][1] in "()" and english[-1][1] in "()"
    assert english[-2][1] in "()" and english[-3][1] == "Y"
    doc.close()


def test_pdf_explicit_alignment_keeps_bilingual_text_whole() -> None:
    doc = pdfium.PdfDocument(_split_pdf(_split_form(align="left")))
    page = doc[0]
    width = page.get_width()
    x, thaana = _thaana_xs_on_line(page, "Full")
    assert x < width / 4 and thaana and max(thaana) < width / 2
    doc.close()


def test_email_splits_bilingual_labels_and_options() -> None:
    form = _split_form()
    msg = emails.receipt_message(
        org_name="Example Office",
        form=form,
        title=form.settings.title,
        reference="#0007",
        submitted=datetime(2026, 11, 1, tzinfo=UTC),
        tz=ZoneInfo("UTC"),
        answers=emails.answers_for_email(form, {"full_name": "Aminath", "program": "ppy"}),
        pdf=None,
    )
    html = msg.html or ""
    assert re.search(r'<td lang="en" dir="ltr" align="left"[^>]*>Full name:</td>', html)
    assert re.search(r'<td lang="dv" dir="rtl" align="right"[^>]*>ފުރިހަމަ ނަން</td>', html)
    assert re.search(r'<td lang="en"[^>]*>Which program did you participate in\?</td>', html)
    assert re.search(r'<td lang="en"[^>]*>\(Practice Parliament for Youth \(PPY\)\)</td>', html)
    # Explicit alignment: one piece.
    left = _split_form(align="left")
    html = (
        emails.receipt_message(
            org_name="Example Office",
            form=left,
            title=left.settings.title,
            reference="#0007",
            submitted=datetime(2026, 11, 1, tzinfo=UTC),
            tz=ZoneInfo("UTC"),
            answers=emails.answers_for_email(left, {"full_name": "Aminath"}),
            pdf=None,
        ).html
        or ""
    )
    assert "<td lang=" not in html
