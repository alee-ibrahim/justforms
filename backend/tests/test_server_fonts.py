"""The operator-supplied Thaana face for server rendering (JUSTFORMS_THAANA_FONT_FILE).

No third-party Thaana font is used here: the "operator font" is a renamed copy of the bundled
Noto Sans Thaana, so the tests can tell which face a document embeds.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fontTools.ttLib import TTFont

from app.config import Settings
from app.pdf import faces
from app.pdf.faces import BUNDLED, thaana_face
from app.pdf.render import PdfInput, render_pdf
from app.schemas.form import Form
from app.sharing import image as og
from app.sharing.service import Preview
from tests.helpers import field

DV_TITLE = "ރަށު ކައުންސިލަށް ހުށަހަޅާ ފޯމު"


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    faces._load.cache_clear()
    yield
    faces._load.cache_clear()


def _font(
    tmp_path: Path, name: str = "Test Thaana", fs_type: int = 0, src: Path | None = None
) -> Path:
    font = TTFont(str(src or faces.BUNDLED_REGULAR))
    ps = name.replace(" ", "") + "-Regular"
    for rec in list(font["name"].names):
        if rec.nameID in (1, 4, 16):
            rec.string = name
        elif rec.nameID == 6:
            rec.string = ps
    font["OS/2"].fsType = fs_type
    out = tmp_path / f"{ps}.ttf"
    font.save(str(out))
    return out


def _settings(path: Path | str, bold: Path | str = "") -> Settings:
    return Settings(environment="test", thaana_font_file=str(path), thaana_font_bold_file=str(bold))


def _pdf(face: faces.ThaanaFace) -> bytes:
    form = Form.model_validate(
        {
            "settings": {"title": DV_TITLE, "language": "dv"},
            "pages": [{"id": "p1", "elements": [field("name", label="ނަން")]}],
        }
    )
    return render_pdf(
        PdfInput(
            org_name="Example Office",
            form_title=DV_TITLE,
            form=form,
            version=1,
            schema_hash="x",
            submission_id="00000000-0000-0000-0000-000000000000",
            seq=1,
            submitted_at=datetime(2026, 10, 23, tzinfo=UTC),
            data={"name": "ޢާއިޝަތު ޢަލީ (Aishath Ali) 7771234"},
            content_hash="y",
            chain_head=None,
            tz=ZoneInfo("UTC"),
            verify_url="http://testserver/v/token",
            thaana=face,
        )
    )


def test_unset_uses_the_bundled_face() -> None:
    assert thaana_face(Settings(environment="test"), "pdf") is BUNDLED
    assert thaana_face(Settings(environment="test"), "image") is BUNDLED
    assert b"NotoSansThaana" in _pdf(BUNDLED)


def test_operator_font_is_embedded_in_pdfs_for_thaana_only(tmp_path: Path) -> None:
    path = _font(tmp_path)
    face = thaana_face(_settings(path), "pdf")
    assert not face.bundled and face.name == "Test Thaana"
    assert face.regular == path and face.bold == path  # no bold file: regular for bold
    assert face.version != BUNDLED.version
    assert face.unicode_range is not None
    assert 0x0780 in face.unicode_range and ord("A") not in face.unicode_range
    pdf = _pdf(face)
    assert b"+TestThaana" in pdf
    assert b"NotoSansThaana" not in pdf
    # Latin letters in a Dhivehi answer keep the Latin face.
    assert b"Inter" in pdf


def test_bold_file_is_used_for_bold(tmp_path: Path) -> None:
    regular = _font(tmp_path)
    bold = _font(tmp_path, "Test Thaana Bold", src=faces.BUNDLED_BOLD)
    face = thaana_face(_settings(regular, bold), "pdf")
    assert face.bold == bold
    assert thaana_face(_settings(regular), "pdf").version != face.version


def test_link_preview_uses_the_face_and_its_version(tmp_path: Path) -> None:
    face = thaana_face(_settings(_font(tmp_path)), "image")
    card = og.Card(
        title=DV_TITLE,
        description=None,
        org_name="Example Council",
        address="forms.example.org/intake",
        rtl=True,
        colors=og.Colors(),
        thaana=face,
    )
    assert b"+TestThaana" in og._draw(card)
    assert og.render(card)[:8] == b"\x89PNG\r\n\x1a\n"

    def version(c: og.Card) -> str:
        return Preview(
            form_id=None,  # type: ignore[arg-type]
            slug="intake",
            title=c.title,
            description="",
            site_name="Example Council",
            language="dv",
            url="https://forms.example.org/intake",
            card=c,
            custom=None,
            logo_version="",
        ).version

    from dataclasses import replace

    # Changing the font makes a new image (cached images are keyed by version).
    assert version(card) != version(replace(card, thaana=BUNDLED))


@pytest.mark.parametrize("kind", ["missing", "not_a_font", "latin_only"])
def test_unusable_files_fall_back_and_warn_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, kind: str
) -> None:
    if kind == "missing":
        path = tmp_path / "nope.ttf"
    elif kind == "not_a_font":
        path = tmp_path / "junk.ttf"
        path.write_bytes(b"\x00\x01\x00\x00" + b"junk" * 100)
    else:
        path = faces.LATIN_REGULAR
    settings = _settings(path)
    with caplog.at_level(logging.WARNING, logger="app.pdf.faces"):
        assert thaana_face(settings, "pdf") is BUNDLED
        assert thaana_face(settings, "pdf") is BUNDLED
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "falling back to Noto Sans Thaana" in warnings[0].getMessage()


def test_no_embedding_licence_keeps_it_out_of_pdfs_only(tmp_path: Path) -> None:
    settings = _settings(_font(tmp_path, fs_type=0x0002))
    assert thaana_face(settings, "pdf") is BUNDLED
    # Link-preview images are rasterised: the font never leaves the server.
    assert thaana_face(settings, "image").name == "Test Thaana"
    # Preview & print embedding (fsType 4) is fine for read-only signed PDFs.
    assert not thaana_face(_settings(_font(tmp_path, "Print Ok", fs_type=0x0004)), "pdf").bundled
    assert thaana_face(_settings(_font(tmp_path, "No Subset", fs_type=0x0100)), "pdf") is BUNDLED
