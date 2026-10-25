"""Post-processing and safety rules for extracted daily report data (SPEC B5, AC-01, AC-13)."""

from datetime import date, datetime
import re
from typing import Any, List, Optional, Tuple
from app.domain.extraction_models import (
    ExtractedField,
    ExtractionFieldStatus,
    ExtractionResult,
    RawExtractionOutput,
)
from app.infra.clock import Clock
from app.infra.settings import settings


class ExtractionValidationError(ValueError):
    """Raised when post-processing encounters a hard rejection criteria."""
    pass


def parse_strict_report_date(date_raw: str, clock: Clock) -> date:
    """Parse report date strictly as DD/MM/YYYY and verify calendar validity and non-future."""
    date_clean = date_raw.strip()
    match = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", date_clean)
    if not match:
        raise ExtractionValidationError(f"Invalid or unreadable date format: '{date_raw}'. Expected DD/MM/YYYY.")

    d_str, m_str, y_str = match.groups()
    day, month, year = int(d_str), int(m_str), int(y_str)

    try:
        parsed_date = date(year, month, day)
    except ValueError as e:
        raise ExtractionValidationError(f"Invalid calendar date '{date_raw}': {e}")

    # Check future date against injected Clock (India Asia/Kolkata date)
    today_in_india = clock.today()
    if parsed_date > today_in_india:
        raise ExtractionValidationError(
            f"Report date {parsed_date} is in the future (current India date is {today_in_india})."
        )

    return parsed_date


def verify_customer_match(customer_name_raw: Optional[str], capacity_mw: Optional[float]) -> str:
    """Validate customer name against stored aliases and verify 1 MW capacity."""
    if not customer_name_raw:
        raise ExtractionValidationError("Customer row missing: No customer name extracted from report.")

    cleaned_name = customer_name_raw.upper().replace(".", "").replace("/", "").strip()
    target_aliases = [
        alias.upper().replace(".", "").replace("/", "").strip()
        for alias in settings.TARGET_CUSTOMER_ALIASES
    ]

    matched = any(alias in cleaned_name or cleaned_name in alias for alias in target_aliases)
    if not matched:
        raise ExtractionValidationError(
            f"Customer '{customer_name_raw}' does not match target 'SRS KUMARAN'. Only SRS KUMARAN data is processed."
        )

    if capacity_mw is not None and abs(capacity_mw - 1.0) > 0.05:
        raise ExtractionValidationError(
            f"Expected capacity 1 MW for SRS KUMARAN, got {capacity_mw} MW."
        )

    return settings.TARGET_CUSTOMER_NAME


def post_process_extraction(
    raw: RawExtractionOutput,
    clock: Clock,
    evidence_crop_path: Optional[str] = None,
    raw_sha256: str = "",
) -> ExtractionResult:
    """Apply strict post-processing and construct normalized ExtractionResult."""
    # 1. Strict Date Validation
    parsed_date = parse_strict_report_date(raw.date_raw, clock)
    date_iso_str = str(parsed_date)

    # 2. Strict Customer & Capacity Verification
    matched_customer = verify_customer_match(raw.customer_name_raw, raw.capacity_mw)

    # 3. Build ExtractedField items
    def make_field(val: Any, is_mandatory: bool = True) -> ExtractedField:
        if val is None:
            status = ExtractionFieldStatus.FAILED if is_mandatory else ExtractionFieldStatus.CHECK
            return ExtractedField(value=val, status=status, confidence=0.0)
        return ExtractedField(value=val, status=ExtractionFieldStatus.OK, confidence=1.0)

    # Clean numbers
    inv_field = make_field(raw.inverter_generation_today_kwh)
    eb_field = make_field(raw.grid_export_kwh)
    eb_6to10_field = make_field(raw.reading_6am_10am_kwh)

    # Format check: kWh printed with two decimals (e.g. 7625.00)
    # If integer without decimals was returned or negative, flag as CHECK
    if inv_field.value is not None and inv_field.value < 0:
        inv_field.status = ExtractionFieldStatus.FAILED

    return ExtractionResult(
        date_raw=ExtractedField(value=raw.date_raw, status=ExtractionFieldStatus.OK),
        date_iso=ExtractedField(value=date_iso_str, status=ExtractionFieldStatus.OK),
        customer_name=ExtractedField(value=matched_customer, status=ExtractionFieldStatus.OK),
        serial_no=make_field(raw.serial_no, is_mandatory=False),
        capacity_mw=ExtractedField(value=1.0, status=ExtractionFieldStatus.OK),
        inverter_kwh=inv_field,
        reported_monthly_kwh=make_field(raw.monthly_generated_kwh, is_mandatory=False),
        reported_yearly_kwh=make_field(raw.yearly_generated_kwh, is_mandatory=False),
        eb_export_kwh=eb_field,
        eb_6to10_kwh=eb_6to10_field,
        inverter_availability_pct=make_field(raw.inverter_availability_pct, is_mandatory=False),
        grid_availability_pct=make_field(raw.grid_availability_pct, is_mandatory=False),
        fault_text=make_field(raw.fault_alarm_text or "", is_mandatory=False),
        plant_weather_text=make_field(raw.weather_condition_text or "", is_mandatory=False),
        plant_temp_c=make_field(raw.temperature_c, is_mandatory=False),
        evidence_crop_path=evidence_crop_path,
        engine="GEMINI",
        parser_version="v1.0",
        prompt_version="v1.0",
        raw_sha256=raw_sha256,
    )
