"""Month lifecycle, calendar utilities, and permission rules."""

import calendar
from datetime import date, datetime, time, timedelta
from typing import List, Tuple
from zoneinfo import ZoneInfo
from app.domain.models import MonthStatus, UserRole

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


def get_month_days_count(year: int, month: int) -> int:
    """Return the exact number of calendar days in a month.
    
    Handles leap years (e.g. Feb 2027 = 28, Feb 2028 = 29, Apr = 30, May = 31).
    """
    _, days = calendar.monthrange(year, month)
    return days


def get_month_calendar_dates(year: int, month: int) -> List[date]:
    """Return a list of all date objects for the calendar month in ascending order."""
    days = get_month_days_count(year, month)
    return [date(year, month, d) for d in range(1, days + 1)]


def format_month_label(year: int, month: int) -> str:
    """Format month for report headers, e.g., 'MAY-2026'."""
    month_abbr = calendar.month_abbr[month].upper()
    return f"{month_abbr}-{year}"


def parse_ym(ym_str: str) -> Tuple[int, int]:
    """Parse 'YYYY-MM' string into (year, month)."""
    parts = ym_str.strip().split("-")
    if len(parts) != 2:
        raise ValueError(f"Invalid YYYY-MM format: '{ym_str}'")
    return int(parts[0]), int(parts[1])


def get_month_close_datetime(year: int, month: int, close_time_str: str = "00:05") -> datetime:
    """Return the exact datetime when the given month should close (1st of next month at close_time IST)."""
    if month == 12:
        next_year = year + 1
        next_month = 1
    else:
        next_year = year
        next_month = month + 1

    hour, minute = [int(p) for p in close_time_str.split(":")]
    return datetime(next_year, next_month, 1, hour, minute, 0, tzinfo=KOLKATA_TZ)


def get_month_lock_datetime(year: int, month: int, grace_days: int = 3) -> datetime:
    """Return the exact datetime when a closed month locks (end of day grace_days in the next month)."""
    if month == 12:
        next_year = year + 1
        next_month = 1
    else:
        next_year = year
        next_month = month + 1

    # End of day grace_days (e.g. 3rd of June 23:59:59.999999 IST)
    return datetime(next_year, next_month, grace_days, 23, 59, 59, 999999, tzinfo=KOLKATA_TZ)


def determine_month_status(
    year: int,
    month: int,
    current_time: datetime,
    close_time_str: str = "00:05",
    grace_days: int = 3,
) -> MonthStatus:
    """Determine whether a month is OPEN, CLOSED, or LOCKED based on current_time in Asia/Kolkata."""
    if current_time.tzinfo is None:
        tz_current = current_time.replace(tzinfo=KOLKATA_TZ)
    else:
        tz_current = current_time.astimezone(KOLKATA_TZ)

    close_dt = get_month_close_datetime(year, month, close_time_str)
    lock_dt = get_month_lock_datetime(year, month, grace_days)

    if tz_current < close_dt:
        return MonthStatus.OPEN
    elif tz_current <= lock_dt:
        return MonthStatus.CLOSED
    else:
        return MonthStatus.LOCKED


def can_modify_month(
    status: MonthStatus,
    role: UserRole,
    has_admin_reason: bool = False,
) -> Tuple[bool, str]:
    """Check if a user with role is permitted to modify a reading in a month with given status."""
    if status == MonthStatus.OPEN:
        return True, ""
    if status == MonthStatus.CLOSED:
        # Both Operator and Admin can edit in grace period
        return True, ""
    if status == MonthStatus.LOCKED:
        if role == UserRole.ADMIN:
            if not has_admin_reason:
                return False, "Admin override of LOCKED month requires a written reason."
            return True, ""
        return False, "Month is LOCKED. Only an Admin can make changes."
    return False, f"Unknown month status: {status}"
