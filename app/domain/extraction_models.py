"""Pydantic schemas and models for structured extraction matching docs/SPEC.md B5."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ExtractionFieldStatus(str, Enum):
    OK = "OK"
    CHECK = "CHECK"
    FAILED = "FAILED"


class RawExtractionOutput(BaseModel):
    """Pydantic schema passed to Gemini for structured JSON generation."""

    date_raw: str = Field(
        ...,
        description="The report date exactly as printed (DD/MM/YYYY) in the top title/date band.",
    )
    customer_name_raw: Optional[str] = Field(
        None,
        description="The customer name exactly as printed in the row (e.g. 'M/s. SRS KUMARAN INDIA PVT LTD').",
    )
    serial_no: Optional[int] = Field(
        None,
        description="The serial number in column 1 (small integer, e.g. 5).",
    )
    capacity_mw: Optional[float] = Field(
        None,
        description="The plant/customer capacity in MW (e.g. 1.0).",
    )
    inverter_generation_today_kwh: Optional[float] = Field(
        None,
        description="Inverter Generation Today in kWh (e.g. 7625.00).",
    )
    monthly_generated_kwh: Optional[float] = Field(
        None,
        description="Monthly Generated in kWh (e.g. 130428.00).",
    )
    yearly_generated_kwh: Optional[float] = Field(
        None,
        description="Yearly Generated in kWh (e.g. 565368.00).",
    )
    grid_export_kwh: Optional[float] = Field(
        None,
        description="Grid Export (kWh) (EB) (e.g. 7452.00).",
    )
    reading_6am_10am_kwh: Optional[float] = Field(
        None,
        description="6am TO 10am Reading - EB Meter (e.g. 1584.00).",
    )
    inverter_availability_pct: Optional[float] = Field(
        None,
        description="Inverter Availability percentage (e.g. 100.0).",
    )
    grid_availability_pct: Optional[float] = Field(
        None,
        description="Grid Availability percentage (e.g. 100.0).",
    )
    fault_alarm_text: Optional[str] = Field(
        "",
        description="Any text in the FAULT / ALARM REPORT column to the right; blank if none.",
    )
    weather_condition_text: Optional[str] = Field(
        "",
        description="Weather condition printed near the bottom (e.g. 'sunny').",
    )
    temperature_c: Optional[float] = Field(
        None,
        description="Temperature in degrees Celsius printed near the bottom (e.g. 35).",
    )


class ExtractedField(BaseModel):
    value: Any
    status: ExtractionFieldStatus = ExtractionFieldStatus.OK
    confidence: float = 1.0
    message: Optional[str] = None


class ExtractionResult(BaseModel):
    """Normalized extraction result holding confidence and verification flags."""

    date_raw: ExtractedField
    date_iso: ExtractedField
    customer_name: ExtractedField
    serial_no: ExtractedField
    capacity_mw: ExtractedField
    inverter_kwh: ExtractedField
    reported_monthly_kwh: ExtractedField
    reported_yearly_kwh: ExtractedField
    eb_export_kwh: ExtractedField
    eb_6to10_kwh: ExtractedField
    inverter_availability_pct: ExtractedField
    grid_availability_pct: ExtractedField
    fault_text: ExtractedField
    plant_weather_text: ExtractedField
    plant_temp_c: ExtractedField
    evidence_crop_path: Optional[str] = None
    engine: str = "GEMINI"
    parser_version: str = "v1.0"
    prompt_version: str = "v1.0"
    raw_sha256: str = ""
