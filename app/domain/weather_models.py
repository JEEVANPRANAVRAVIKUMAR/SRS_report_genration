"""Domain models and data structures for weather metrics and performance insights (SPEC B7)."""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class WeatherQuality(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class PerformanceFlag(str, Enum):
    NORMAL = "NORMAL"
    BELOW_EXPECTED = "Below expected for the sunshine"
    CHECK_DATA = "Check data"
    INSUFFICIENT_DATA = "Insufficient baseline data"


@dataclass
class DaytimeWeatherSummary:
    """Summary of daytime (06:00-18:00 IST), morning (06:00-10:00 IST), and 24h metrics."""
    report_date: date
    mean_daytime_cloud_pct: float
    total_solar_energy_kwh_per_m2: float
    morning_mean_cloud_pct: float
    morning_solar_energy_kwh_per_m2: float
    rain_24h_mm: float
    max_temperature_c: float
    sky_class: str
    rain_class: Optional[str]
    auto_remark: str
    quality: WeatherQuality = WeatherQuality.FINAL
    provider: str = "open-meteo"
    raw_response: Optional[Dict[str, Any]] = None


@dataclass
class YieldInsight:
    """Daily performance insight derived from generation vs solar irradiance."""
    report_date: date
    inverter_kwh: float
    solar_energy_kwh_per_m2: float
    yield_index: float
    baseline_yield_index: Optional[float]
    expected_kwh: Optional[float]
    ratio_to_expected: Optional[float]
    flag: PerformanceFlag
    is_clear_day: bool
    explanation: str
