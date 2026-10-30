"""Reference numbers (``#0042``): per form, from a counter on the form row.

``forms.last_seq`` is the highest number the form has handed out and never goes down. Numbers
are not taken from the submissions still stored, so erasing the newest submission (the trash,
a retention period) does not free its number: an old PDF or verify page for it can never point
at a different submission.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FormRecord, Submission


async def allocate(db: AsyncSession, form_id: uuid.UUID, count: int = 1) -> int:
    """Reserve ``count`` consecutive numbers on the form and return the first.

    One ``UPDATE ... RETURNING``: the row lock it takes is held until the caller's transaction
    ends, so concurrent submits on the same form queue up and each gets its own numbers. A
    rollback gives the numbers back. Numbers already held by stored submissions are skipped
    too, should a row ever have been written without the counter."""
    if count < 1:
        raise ValueError("count must be at least 1")
    stored = (
        select(func.coalesce(func.max(Submission.seq), 0))
        .where(Submission.form_id == form_id)
        .scalar_subquery()
    )
    last = await db.scalar(
        update(FormRecord)
        .where(FormRecord.id == form_id)
        .values(last_seq=func.greatest(FormRecord.last_seq, stored) + count)
        .returning(FormRecord.last_seq)
        .execution_options(synchronize_session=False)
    )
    if last is None:
        raise LookupError("form_not_found")
    return int(last) - count + 1
