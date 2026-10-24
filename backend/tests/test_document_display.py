"""How answers read in documents people open: the respondent's PDF and the emails."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.answers import answer_text, format_phone
from app.notifications.emails import answers_for_email, receipt_message
from app.pdf.render import (
    PDF_WORDS,
    SIGNATURE_WIDTH,
    PdfInput,
    SignatureInfo,
    _Doc,
    _png_size,
    _signature,
)
from app.schemas.form import Form
from app.signatures.render import parse_strokes, render_png
from tests.helpers import field


def _form(language: str, *elements: dict[str, Any]) -> Form:
    return Form.model_validate(
        {
            "settings": {"title": "Application", "language": language},
            "pages": [{"id": "p1", "elements": list(elements)}],
        }
    )


def test_phone_numbers_are_grouped_for_display_only() -> None:
    assert format_phone("+9607771234") == "+960 777 1234"
    assert format_phone("+447700900123") == "+447700900123"
    assert format_phone("+96077712345") == "+96077712345"
    phone = _form("en", field("phone", "phone")).pages[0].elements[0]
    assert answer_text(phone, "+9607771234", "en") == "+9607771234"  # type: ignore[arg-type]
    assert answer_text(phone, "+9607771234", "en", display=True) == "+960 777 1234"  # type: ignore[arg-type]


def test_footer_has_no_middle_dot() -> None:
    assert PDF_WORDS["signed_verify"] == "Digitally signed. Verify at"
    assert all("·" not in w for w in PDF_WORDS.values())


def _signature_doc(language: str) -> _Doc:
    src = PdfInput(
        org_name="Example Office",
        form_title="Application",
        form=_form(language, field("name")),
        version=1,
        schema_hash="x",
        submission_id="00000000-0000-0000-0000-000000000000",
        seq=1,
        submitted_at=datetime(2026, 10, 23, tzinfo=UTC),
        data={},
        content_hash="y",
        chain_head=None,
        tz=ZoneInfo("UTC"),
        verify_url="http://testserver/v/token",
    )
    doc = _Doc(src, None)
    doc.add_page()
    return doc


def _sig() -> SignatureInfo:
    points = [
        [round(0.1 + 0.6 * i / 40, 4), round(0.5 + 0.2 * math.sin(i / 3), 4), i * 16, 0.5]
        for i in range(40)
    ]
    png = render_png(parse_strokes([points], 360, 176))
    return SignatureInfo("sign", png, "I confirm the information in this form is true.")


def test_signature_stays_with_its_statement() -> None:
    for language in ("en", "dv"):
        # Room for everything: label, statement and image stay on page 1.
        doc = _signature_doc(language)
        _signature(doc, "Signature", _sig())
        assert doc.page_no() == 1
        # Near the bottom the statement would fit but the image would not: the page breaks
        # before the label, so the label, statement and image all land on page 2 together.
        sig = _sig()
        size = _png_size(sig.png)
        assert size is not None
        image_h = SIGNATURE_WIDTH * size[1] / size[0]
        doc = _signature_doc(language)
        doc.set_y(doc.page_break_trigger - 15)
        _signature(doc, "Signature", sig)
        assert doc.page_no() == 2
        # Page 2 holds more than the image and its baseline: the label and statement too.
        assert doc.get_y() > doc.t_margin + image_h + 5 + 8


def test_dhivehi_email_answers_use_the_thaana_face_and_scale() -> None:
    def html(language: str) -> str:
        form = _form(language, field("name", label="Name"), field("phone", "phone", label="Phone"))
        answers = answers_for_email(form, {"name": "Aminath", "phone": "+9607771234"})
        return (
            receipt_message(
                org_name="Example Office",
                form=form,
                title="Application",
                reference="#0001",
                submitted=datetime(2026, 10, 23, tzinfo=UTC),
                tz=ZoneInfo("UTC"),
                answers=answers,
                pdf=None,
            ).html
            or ""
        )

    dv = html("dv")
    assert '<td lang="dv"' in dv and "Noto Sans Thaana" in dv
    assert "font-size:16px" in dv and "font-size:18px" in dv
    assert "+960 777 1234" in dv
    en = html("en")
    assert "Noto Sans Thaana" not in en and "font-size:13px" in en
