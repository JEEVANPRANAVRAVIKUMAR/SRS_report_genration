"""Pure domain models and enum types."""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"


class MonthStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    LOCKED = "LOCKED"


class EntryMethod(str, Enum):
    IMAGE = "IMAGE"
    MANUAL = "MANUAL"
    IMPORT = "IMPORT"


class ReadingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class RuleSeverity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass
class ValidationFinding:
    rule_number: int
    rule_name: str
    severity: RuleSeverity
    message: str
    field: Optional[str] = None


@dataclass
class DailyReadingInput:
    report_date: date
    inverter_kwh: Optional[float]
    eb_export_kwh: Optional[float]
    eb_6to10_kwh: Optional[float]
    reported_monthly_kwh: Optional[float] = None
    reported_yearly_kwh: Optional[float] = None
    inverter_availability_pct: Optional[float] = 100.0
    grid_availability_pct: Optional[float] = 100.0
    fault_text: Optional[str] = ""
    plant_weather_text: Optional[str] = ""
    plant_temp_c: Optional[float] = None
    manual_remark: Optional[str] = ""
    auto_remark: Optional[str] = ""
    entry_method: EntryMethod = EntryMethod.MANUAL
    source_upload_id: Optional[int] = None
    actor_label: str = "Operator"


@dataclass
class DailyTotals:
    report_date: date
    inverter_kwh: float
    running_inverter_total: float
    eb_export_kwh: float
    running_eb_total: float
    eb_6to10_kwh: float
    manual_remark: str = ""
    auto_remark: str = ""
    combined_remark: str = ""


@dataclass
class MonthSummary:
    year: int
    month: int
    total_days: int
    days_recorded: int
    missing_dates: List[date]
    total_inverter_kwh: float
    total_eb_kwh: float
    average_daily_inverter_kwh: float
    status: MonthStatus
    pdf_revision: int = 1
