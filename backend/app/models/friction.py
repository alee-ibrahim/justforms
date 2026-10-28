"""Respondent friction counters (docs/features.md "Where people get stuck").

Anonymous, aggregated counts per form, version, day and metric. No answer values, no
respondent identity, no per-visit rows: the per-visit id only de-duplicates in Redis for a day
(``app.insights.friction``).
"""

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class FormFriction(Base):
    """One counter. ``metric``: ``view`` (a visit reached ``page_id``), ``start`` (a visit
    answered its first question), ``error`` (a visit saw ``code`` on ``field_id`` on
    ``page_id``) or ``submit`` (a submission was received)."""

    __tablename__ = "form_friction"

    form_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forms.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    metric: Mapped[str] = mapped_column(String(16), primary_key=True)
    page_id: Mapped[str] = mapped_column(String(63), primary_key=True, default="")
    field_id: Mapped[str] = mapped_column(String(63), primary_key=True, default="")
    code: Mapped[str] = mapped_column(String(32), primary_key=True, default="")
    count: Mapped[int] = mapped_column(Integer, default=0)
