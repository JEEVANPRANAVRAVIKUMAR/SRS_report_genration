"""Pure validation rules 1 through 12 from docs/SPEC.md Section B6."""

from datetime import date
from typing import List, Optional, Sequence
from app.domain.models import (
    DailyReadingInput,
    RuleSeverity,
    ValidationFinding,
)


class ValidationReport:
    """Encapsulates validation findings for a reading."""

    def __init__(self, findings: List[ValidationFinding]) -> None:
        self.findings = findings

    @property
    def errors(self) -> List[ValidationFinding]:
        return [f for f in self.findings if f.severity == RuleSeverity.ERROR]

    @property
    def warnings(self) -> List[ValidationFinding]:
        return [f for f in self.findings if f.severity == RuleSeverity.WARNING]

    @property
    def infos(self) -> List[ValidationFinding]:
        return [f for f in self.findings if f.severity == RuleSeverity.INFO]

    @property
    def is_valid(self) -> bool:
        """Returns True if there are zero blocking errors."""
        return len(self.errors) == 0

    def can_accept(self, is_admin: bool = False, admin_override_reason: str = "") -> bool:
        """Check if reading can be accepted.
        
        Admin can override Rule 3 (EB export > inverter generation) with a written reason.
        """
        for err in self.errors:
            if err.rule_number == 3 and is_admin and admin_override_reason.strip():
                continue
            return False
        return True


def validate_reading(
    reading: DailyReadingInput,
    computed_month_to_date_inverter: Optional[float] = None,
    best_inverter_last_60_days: Optional[float] = None,
    weather_service_temp_c: Optional[float] = None,
    missing_dates_in_month: Optional[Sequence[date]] = None,
    eb_mf: int = 12,
    max_daily_inverter_kwh: float = 12000.0,
    inverter_spike_ratio: float = 1.3,
    eb_ratio_min: float = 0.95,
    eb_ratio_max: float = 1.00,
    temp_tolerance_c: float = 6.0,
) -> ValidationReport:
    """Pure validator applying Rules 1 to 12 from docs/SPEC.md Section B6."""
    findings: List[ValidationFinding] = []

    # Rule 1: Date, inverter, EB export and 6am-10am are present (Error)
    missing_fields = []
    if reading.report_date is None:
        missing_fields.append("report_date")
    if reading.inverter_kwh is None:
        missing_fields.append("inverter_kwh")
    if reading.eb_export_kwh is None:
        missing_fields.append("eb_export_kwh")
    if reading.eb_6to10_kwh is None:
        missing_fields.append("eb_6to10_kwh")

    if missing_fields:
        findings.append(
            ValidationFinding(
                rule_number=1,
                rule_name="mandatory_fields_present",
                severity=RuleSeverity.ERROR,
                message=f"Missing mandatory field(s): {', '.join(missing_fields)}",
                field=missing_fields[0],
            )
        )
        return ValidationReport(findings)

    inv = float(reading.inverter_kwh)
    eb = float(reading.eb_export_kwh)
    eb_6to10 = float(reading.eb_6to10_kwh)

    # Rule 2: All numbers are 0 or more (Error)
    negative_fields = []
    if inv < 0:
        negative_fields.append(f"inverter_kwh ({inv})")
    if eb < 0:
        negative_fields.append(f"eb_export_kwh ({eb})")
    if eb_6to10 < 0:
        negative_fields.append(f"eb_6to10_kwh ({eb_6to10})")
    if reading.reported_monthly_kwh is not None and reading.reported_monthly_kwh < 0:
        negative_fields.append(f"reported_monthly_kwh ({reading.reported_monthly_kwh})")
    if reading.reported_yearly_kwh is not None and reading.reported_yearly_kwh < 0:
        negative_fields.append(f"reported_yearly_kwh ({reading.reported_yearly_kwh})")

    if negative_fields:
        findings.append(
            ValidationFinding(
                rule_number=2,
                rule_name="non_negative_numbers",
                severity=RuleSeverity.ERROR,
                message=f"Negative numbers not permitted: {', '.join(negative_fields)}",
                field="numbers",
            )
        )

    # Rule 3: EB export is not above inverter generation (Error, Admin override with reason)
    if eb > inv:
        findings.append(
            ValidationFinding(
                rule_number=3,
                rule_name="eb_export_not_above_inverter",
                severity=RuleSeverity.ERROR,
                message=f"EB export ({eb}) cannot exceed inverter generation ({inv})",
                field="eb_export_kwh",
            )
        )

    # Rule 4: EB divided by inverter is between 0.95 and 1.00 (Warning)
    if inv > 0:
        ratio = eb / inv
        if ratio < eb_ratio_min or ratio > eb_ratio_max:
            findings.append(
                ValidationFinding(
                    rule_number=4,
                    rule_name="eb_inverter_ratio",
                    severity=RuleSeverity.WARNING,
                    message=f"EB/inverter ratio {ratio:.3f} outside expected range [{eb_ratio_min:.2f}, {eb_ratio_max:.2f}]",
                    field="eb_export_kwh",
                )
            )

    # Rule 5: EB and 6am-10am are multiples of EB_MF (default 12) (Warning)
    if eb_mf > 1:
        # Check integer divisibility or close to integer within small floating tolerance
        if abs(eb % eb_mf) > 1e-4:
            findings.append(
                ValidationFinding(
                    rule_number=5,
                    rule_name="eb_multiple_of_mf",
                    severity=RuleSeverity.WARNING,
                    message=f"EB export {eb} is not a multiple of {eb_mf}",
                    field="eb_export_kwh",
                )
            )
        if abs(eb_6to10 % eb_mf) > 1e-4:
            findings.append(
                ValidationFinding(
                    rule_number=5,
                    rule_name="eb_6to10_multiple_of_mf",
                    severity=RuleSeverity.WARNING,
                    message=f"6am-10am reading {eb_6to10} is not a multiple of {eb_mf}",
                    field="eb_6to10_kwh",
                )
            )

    # Rule 6: 6am-10am is not above EB export (Error)
    if eb_6to10 > eb:
        findings.append(
            ValidationFinding(
                rule_number=6,
                rule_name="eb_6to10_not_above_eb_export",
                severity=RuleSeverity.ERROR,
                message=f"6am-10am reading ({eb_6to10}) cannot exceed total daily EB export ({eb})",
                field="eb_6to10_kwh",
            )
        )

    # Rule 7: Inverter is at most 12,000 kWh (Error); above 1.3 times best day in 60 days (Warning)
    if inv > max_daily_inverter_kwh:
        findings.append(
            ValidationFinding(
                rule_number=7,
                rule_name="inverter_max_daily_capacity",
                severity=RuleSeverity.ERROR,
                message=f"Inverter generation {inv} exceeds plant physical ceiling {max_daily_inverter_kwh} kWh",
                field="inverter_kwh",
            )
        )
    elif best_inverter_last_60_days and best_inverter_last_60_days > 0:
        threshold = best_inverter_last_60_days * inverter_spike_ratio
        if inv > threshold:
            findings.append(
                ValidationFinding(
                    rule_number=7,
                    rule_name="inverter_spike_suspicious",
                    severity=RuleSeverity.WARNING,
                    message=f"Inverter generation {inv} is unusually high (> {inverter_spike_ratio}x 60-day max {best_inverter_last_60_days})",
                    field="inverter_kwh",
                )
            )

    # Rule 8: Zero generation or zero export (Warning: 'outage? add a remark')
    if inv == 0 or eb == 0:
        findings.append(
            ValidationFinding(
                rule_number=8,
                rule_name="zero_generation_or_export",
                severity=RuleSeverity.WARNING,
                message="Zero generation or zero export detected. Outage? Please add a remark.",
                field="inverter_kwh" if inv == 0 else "eb_export_kwh",
            )
        )

    # Rule 9: Computed month-to-date total vs plant's 'Monthly Generated' (tolerance 1 kWh)
    if reading.reported_monthly_kwh is not None and computed_month_to_date_inverter is not None:
        rep_month = float(reading.reported_monthly_kwh)
        comp_month = float(computed_month_to_date_inverter)
        diff = rep_month - comp_month
        if diff > 1.0:
            findings.append(
                ValidationFinding(
                    rule_number=9,
                    rule_name="plant_monthly_higher_missing_days",
                    severity=RuleSeverity.INFO,
                    message=f"Plant reports {rep_month:.2f} kWh, computed is {comp_month:.2f} kWh (gap of {diff:.2f} kWh; missing days?)",
                    field="reported_monthly_kwh",
                )
            )
        elif diff < -1.0:
            findings.append(
                ValidationFinding(
                    rule_number=9,
                    rule_name="computed_monthly_higher_duplicate_digit",
                    severity=RuleSeverity.WARNING,
                    message=f"Computed total {comp_month:.2f} kWh exceeds plant reported {rep_month:.2f} kWh by {abs(diff):.2f} kWh (possible duplicate or wrong digit)",
                    field="reported_monthly_kwh",
                )
            )

    # Rule 10: Availability below 100% or fault text not empty (Warning and prompt to add remark)
    inv_avail = reading.inverter_availability_pct if reading.inverter_availability_pct is not None else 100.0
    grid_avail = reading.grid_availability_pct if reading.grid_availability_pct is not None else 100.0
    fault = (reading.fault_text or "").strip()

    if inv_avail < 100.0 or grid_avail < 100.0 or fault:
        reasons = []
        if inv_avail < 100.0:
            reasons.append(f"Inverter availability {inv_avail}%")
        if grid_avail < 100.0:
            reasons.append(f"Grid availability {grid_avail}%")
        if fault:
            reasons.append(f"Fault report: '{fault}'")
        findings.append(
            ValidationFinding(
                rule_number=10,
                rule_name="availability_drop_or_fault",
                severity=RuleSeverity.WARNING,
                message=f"Reduced availability or fault ({'; '.join(reasons)}). Please add a remark.",
                field="fault_text",
            )
        )

    # Rule 11: Gaps between recorded dates (Dashboard list of missing dates)
    if missing_dates_in_month:
        missing_count = len(missing_dates_in_month)
        date_strs = [d.strftime("%d-%b") for d in missing_dates_in_month[:5]]
        preview = ", ".join(date_strs) + ("..." if missing_count > 5 else "")
        findings.append(
            ValidationFinding(
                rule_number=11,
                rule_name="gaps_in_recorded_dates",
                severity=RuleSeverity.INFO,
                message=f"{missing_count} missing date(s) in month: {preview}",
                field="report_date",
            )
        )

    # Rule 12: Plant-reported temp differs from weather-service temp by > 6°C (Info)
    if reading.plant_temp_c is not None and weather_service_temp_c is not None:
        diff_temp = abs(reading.plant_temp_c - weather_service_temp_c)
        if diff_temp > temp_tolerance_c:
            findings.append(
                ValidationFinding(
                    rule_number=12,
                    rule_name="plant_weather_temp_mismatch",
                    severity=RuleSeverity.INFO,
                    message=f"Plant temperature ({reading.plant_temp_c}°C) differs from weather service ({weather_service_temp_c}°C) by {diff_temp:.1f}°C (> {temp_tolerance_c}°C)",
                    field="plant_temp_c",
                )
            )

    return ValidationReport(findings)
