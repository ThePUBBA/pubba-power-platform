"""Pure dashboard state validation and request-boundary helpers."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class DashboardStateError(ValueError):
    pass


def custom_date_range(
    start_date: date, end_date: date, timezone_name: str
) -> tuple[datetime, datetime]:
    if end_date < start_date:
        raise DashboardStateError("End date must be on or after start date.")
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise DashboardStateError(f"Unknown timezone: {timezone_name}") from exc
    return (
        datetime.combine(start_date, time.min, tzinfo=zone),
        datetime.combine(end_date, time.max, tzinfo=zone),
    )


def is_empty_summary(summary: dict) -> bool:
    return (
        summary["fleet"]["active_assets"] == 0
        and summary["operations"]["total_dispatches"] == 0
    )

