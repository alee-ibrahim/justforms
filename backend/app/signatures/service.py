"""Signatures on submit: parse, re-render, store with their audit data (DESIGN 9.1-9.2).

The answer value sent by the pad is ``{strokes, width, height, dpr?, signedAt?}``. After the
submit it is replaced by ``{"signatureId": ...}``; the strokes, the server-rendered SVG/PNG
and the audit data (times, IP, user agent, the statement shown) live in ``signatures``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ids import uuid7
from app.logic.index import FormIndex
from app.models import Signature, Submission
from app.schemas.form import Form, SignatureField
from app.signatures.render import SignatureError, Strokes, parse_strokes, render_png, render_svg
from app.storage import Storage


@dataclass
class Prepared:
    field: SignatureField
    strokes: Strokes
    signed_at: datetime | None
    dpr: float | None


def _client_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _dpr(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool) and 0.25 <= value <= 10:
        return float(value)
    return None


def signature_fields(form: Form) -> list[SignatureField]:
    return [
        info.element
        for info in FormIndex.build(form).elements.values()
        if isinstance(info.element, SignatureField)
    ]


def prepare(form: Form, data: dict[str, Any]) -> tuple[list[Prepared], list[dict[str, Any]]]:
    """Parse every signature answer in ``data`` (visible answers only)."""
    prepared: list[Prepared] = []
    errors: list[dict[str, Any]] = []
    for field in signature_fields(form):
        value = data.get(field.id)
        if not isinstance(value, dict):
            continue
        try:
            strokes = parse_strokes(value.get("strokes"), value.get("width"), value.get("height"))
        except SignatureError as exc:
            errors.append({"field": field.id, "code": exc.code})
            continue
        prepared.append(
            Prepared(field, strokes, _client_time(value.get("signedAt")), _dpr(value.get("dpr")))
        )
    return prepared, errors


async def store(
    db: AsyncSession,
    storage: Storage,
    sub: Submission,
    prepared: list[Prepared],
    *,
    ip: str | None,
    user_agent: str | None,
    received_at: datetime,
) -> list[Signature]:
    """Render and store each signature, and point the answer at its record."""
    rows: list[Signature] = []
    for p in prepared:
        sig_id: uuid.UUID = uuid7()
        base = f"signatures/{sub.id}/{p.field.id}"
        await storage.put(f"{base}.svg", render_svg(p.strokes), content_type="image/svg+xml")
        await storage.put(f"{base}.png", render_png(p.strokes), content_type="image/png")
        row = Signature(
            id=sig_id,
            submission_id=sub.id,
            field_id=p.field.id,
            strokes=p.strokes.strokes,
            strokes_sha256=p.strokes.sha256,
            svg_key=f"{base}.svg",
            png_key=f"{base}.png",
            pad_width=p.strokes.pad_width,
            pad_height=p.strokes.pad_height,
            device_pixel_ratio=p.dpr,
            signed_at=p.signed_at,
            received_at=received_at,
            ip=ip,
            user_agent=user_agent,
            attestation_text=p.field.attestation or "",
            language=sub.language,
        )
        db.add(row)
        rows.append(row)
        # Reassign (not mutate) so the change to the JSONB column is saved.
        sub.data = {**sub.data, p.field.id: {"signatureId": str(sig_id)}}
    return rows
