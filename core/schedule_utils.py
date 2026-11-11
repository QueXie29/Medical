"""Helpers for deciding whether a schedule slot is still usable today."""

from __future__ import annotations

import datetime

from django.utils import timezone


SHIFT_END_TIMES = {
    "morning": datetime.time(12, 0),
    "afternoon": datetime.time(18, 0),
}


def local_now(now=None):
    if now is None:
        return timezone.localtime()
    if timezone.is_aware(now):
        return timezone.localtime(now)
    return timezone.make_aware(now, timezone.get_current_timezone())


def is_schedule_shift_available(work_date, shift: str, *, now=None) -> bool:
    """Return whether a schedule date/shift has not expired in local time."""
    current = local_now(now)
    today = current.date()
    if work_date > today:
        return True
    if work_date < today:
        return False

    end_time = SHIFT_END_TIMES.get(shift)
    if end_time is None:
        return False
    current_time = current.time().replace(tzinfo=None)
    return current_time < end_time


def available_shift_values_for_date(work_date, *, now=None) -> list[str]:
    """List shift values that are still available for a specific date."""
    return [
        shift
        for shift in SHIFT_END_TIMES
        if is_schedule_shift_available(work_date, shift, now=now)
    ]


def expired_schedule_message() -> str:
    return "该班次已过可预约时间；当天上午号源需在 12:00 前处理，下午号源需在 18:00 前处理。"
