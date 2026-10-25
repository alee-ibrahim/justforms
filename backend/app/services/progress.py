"""Saved progress on the respondent's device: a per-form setting read by the public form."""

from __future__ import annotations

from typing import Any

DEFAULT_SAVE_PROGRESS_DAYS = 7
MAX_SAVE_PROGRESS_DAYS = 90


def progress_out(settings: dict[str, Any] | None) -> dict[str, Any]:
    """The setting as FormOut fields: on by default, kept for 7 days."""
    s = settings or {}
    days = s.get("saveProgressDays", DEFAULT_SAVE_PROGRESS_DAYS)
    valid = isinstance(days, int) and not isinstance(days, bool)
    if not valid or not 1 <= days <= MAX_SAVE_PROGRESS_DAYS:
        days = DEFAULT_SAVE_PROGRESS_DAYS
    return {"save_progress": bool(s.get("saveProgress", True)), "save_progress_days": days}


def save_progress_days(settings: dict[str, Any] | None) -> int | None:
    """Days a respondent's saved answers are kept in their browser; None when turned off."""
    out = progress_out(settings)
    return out["save_progress_days"] if out["save_progress"] else None
