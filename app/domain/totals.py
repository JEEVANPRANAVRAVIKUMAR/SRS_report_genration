"""Pure domain logic for calculating running totals, averages, and missing date gaps."""

import calendar
from datetime import date, timedelta
from typing import Dict, List, Sequence, Tuple
from app.domain.models import DailyReadingInput, DailyTotals, MonthStatus, MonthSummary


def calculate_running_totals(
    readings: Sequence[DailyReadingInput],
    remark_mode: str = "both",
) -> List[DailyTotals]:
    """Calculate running totals for a sequence of daily readings strictly in date order.
    
    Running totals are computed from day 1 of the month for each reading.
    """
    sorted_readings = sorted(readings, key=lambda r: r.report_date)
    results: List[DailyTotals] = []

    running_inv = 0.0
    running_eb = 0.0

    current_month_key: Tuple[int, int] | None = None

    for r in sorted_readings:
        month_key = (r.report_date.year, r.report_date.month)
        if current_month_key != month_key:
            current_month_key = month_key
            running_inv = 0.0
            running_eb = 0.0

        inv = float(r.inverter_kwh or 0.0)
        eb = float(r.eb_export_kwh or 0.0)
        eb_6to10 = float(r.eb_6to10_kwh or 0.0)

        running_inv += inv
        running_eb += eb

        # Compose combined remark according to remark_mode
        manual = (r.manual_remark or "").strip()
        auto = (r.auto_remark or "").strip()
        if remark_mode == "manual_only":
            combined = manual
        elif remark_mode == "auto_only":
            combined = auto
        else:
            if manual and auto:
                combined = f"{manual}. {auto}"
            else:
                combined = manual or auto

        results.append(
            DailyTotals(
                report_date=r.report_date,
                inverter_kwh=inv,
                running_inverter_total=round(running_inv, 2),
                eb_export_kwh=eb,
                running_eb_total=round(running_eb, 2),
                eb_6to10_kwh=eb_6to10,
                manual_remark=manual,
                auto_remark=auto,
                combined_remark=combined,
            )
        )

    return results


def find_missing_dates_in_range(
    start_date: date,
    end_date: date,
    recorded_dates: Sequence[date],
) -> List[date]:
    """Find all dates between start_date and end_date (inclusive) missing from recorded_dates."""
    recorded_set = set(recorded_dates)
    missing: List[date] = []
    curr = start_date
    while curr <= end_date:
        if curr not in recorded_set:
            missing.append(curr)
        curr += timedelta(days=1)
    return missing


def summarize_month(
    year: int,
    month: int,
    readings: Sequence[DailyReadingInput],
    status: MonthStatus = MonthStatus.OPEN,
    pdf_revision: int = 1,
    up_to_date: date | None = None,
) -> MonthSummary:
    """Summarize a calendar month's generation, totals, averages, and missing days."""
    _, total_days = calendar.monthrange(year, month)
    first_of_month = date(year, month, 1)
    last_of_month = date(year, month, total_days)

    month_readings = [
        r for r in readings if r.report_date.year == year and r.report_date.month == month
    ]

    recorded_dates = [r.report_date for r in month_readings]
    effective_end = up_to_date if (up_to_date and up_to_date <= last_of_month) else last_of_month
    missing = find_missing_dates_in_range(first_of_month, effective_end, recorded_dates)

    total_inv = sum(float(r.inverter_kwh or 0.0) for r in month_readings)
    total_eb = sum(float(r.eb_export_kwh or 0.0) for r in month_readings)
    count = len(month_readings)
    avg_inv = (total_inv / count) if count > 0 else 0.0

    return MonthSummary(
        year=year,
        month=month,
        total_days=total_days,
        days_recorded=count,
        missing_dates=missing,
        total_inverter_kwh=round(total_inv, 2),
        total_eb_kwh=round(total_eb, 2),
        average_daily_inverter_kwh=round(avg_inv, 2),
        status=status,
        pdf_revision=pdf_revision,
    )
