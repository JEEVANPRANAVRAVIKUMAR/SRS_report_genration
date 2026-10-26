"""Pure domain logic for computing daytime weather metrics, yield index, and performance insights (SPEC B7)."""

from datetime import date
import statistics
from typing import List, Optional, Sequence, Tuple
from app.domain.remarks import build_weather_remark, classify_rain, classify_sky
from app.domain.weather_models import (
    DaytimeWeatherSummary,
    PerformanceFlag,
    WeatherQuality,
    YieldInsight,
)


def compute_daytime_metrics(
    report_date: date,
    temperatures_2m: Sequence[float],
    cloud_covers_pct: Sequence[float],
    precipitations_mm: Sequence[float],
    shortwave_radiations_w_m2: Sequence[float],
    quality: WeatherQuality = WeatherQuality.FINAL,
    raw_response: Optional[dict] = None,
) -> DaytimeWeatherSummary:
    """Compute daytime (06:00-18:00 IST), morning (06:00-10:00 IST), and 24-hour summary metrics.
    
    Expected 24 hourly entries per day (indices 0 to 23).
    - Daytime window: index 6 to 17 inclusive (06:00 to 18:00 IST, 12 hours)
    - Morning window: index 6 to 9 inclusive (06:00 to 10:00 IST, 4 hours)
    """
    if len(temperatures_2m) < 24:
        raise ValueError(f"Expected 24 hourly readings, got {len(temperatures_2m)}")

    # Daytime window: hours 6..17 (06:00 to 18:00 IST)
    daytime_clouds = cloud_covers_pct[6:18]
    mean_daytime_cloud = round(statistics.mean(daytime_clouds), 1)

    # Solar energy: sum of hourly W/m2 / 1000 = kWh/m2
    daytime_radiation_w = shortwave_radiations_w_m2[6:18]
    total_daytime_solar_kwh = round(sum(daytime_radiation_w) / 1000.0, 3)

    # Morning window: hours 6..9 (06:00 to 10:00 IST)
    morning_clouds = cloud_covers_pct[6:10]
    morning_mean_cloud = round(statistics.mean(morning_clouds), 1)
    morning_radiation_w = shortwave_radiations_w_m2[6:10]
    morning_solar_kwh = round(sum(morning_radiation_w) / 1000.0, 3)

    # 24-hour metrics
    rain_24h = round(sum(precipitations_mm), 1)
    max_temp = round(max(temperatures_2m), 1)

    sky_class = classify_sky(mean_daytime_cloud)
    rain_class = classify_rain(rain_24h)
    auto_remark = build_weather_remark(
        mean_daytime_cloud_pct=mean_daytime_cloud,
        rain_24h_mm=rain_24h,
        max_temp_c=max_temp,
    )

    return DaytimeWeatherSummary(
        report_date=report_date,
        mean_daytime_cloud_pct=mean_daytime_cloud,
        total_solar_energy_kwh_per_m2=total_daytime_solar_kwh,
        morning_mean_cloud_pct=morning_mean_cloud,
        morning_solar_energy_kwh_per_m2=morning_solar_kwh,
        rain_24h_mm=rain_24h,
        max_temperature_c=max_temp,
        sky_class=sky_class,
        rain_class=rain_class,
        auto_remark=auto_remark,
        quality=quality,
        raw_response=raw_response,
    )


def compute_yield_index(inverter_kwh: float, solar_energy_kwh_per_m2: float) -> float:
    """Calculate yield index: inverter kWh divided by solar energy in kWh/m2."""
    if solar_energy_kwh_per_m2 <= 0.0:
        return 0.0
    return round(inverter_kwh / solar_energy_kwh_per_m2, 2)


def is_clear_day(mean_daytime_cloud_pct: float, rain_24h_mm: float) -> bool:
    """A clear day has mean daytime cloud cover < 30% and no rain (< 0.1 mm)."""
    return mean_daytime_cloud_pct < 30.0 and rain_24h_mm < 0.1


def calculate_yield_baseline(clear_day_yield_indices: Sequence[float]) -> Optional[float]:
    """Calculate baseline yield index: median of the last 30 clear days.
    
    Strict SPEC rule: ONLY valid when at least 7 such clear days exist!
    """
    if len(clear_day_yield_indices) < 7:
        return None
    # Consider at most the last 30 clear days
    sample = clear_day_yield_indices[-30:]
    return round(statistics.median(sample), 2)


def evaluate_performance_insight(
    report_date: date,
    inverter_kwh: float,
    solar_energy_kwh_per_m2: float,
    mean_daytime_cloud_pct: float,
    rain_24h_mm: float,
    baseline_yield_index: Optional[float],
) -> YieldInsight:
    """Evaluate performance insight (Review screen & Insights page only, never printed in PDF).
    
    Rules:
    - Expected kWh = baseline * day's solar energy
    - Flag 'Below expected for the sunshine' when actual < 85% of expected
    - Flag 'Check data' when actual > 115% of expected
    """
    yield_idx = compute_yield_index(inverter_kwh, solar_energy_kwh_per_m2)
    clear_day = is_clear_day(mean_daytime_cloud_pct, rain_24h_mm)

    if baseline_yield_index is None:
        return YieldInsight(
            report_date=report_date,
            inverter_kwh=inverter_kwh,
            solar_energy_kwh_per_m2=solar_energy_kwh_per_m2,
            yield_index=yield_idx,
            baseline_yield_index=None,
            expected_kwh=None,
            ratio_to_expected=None,
            flag=PerformanceFlag.INSUFFICIENT_DATA,
            is_clear_day=clear_day,
            explanation="Fewer than 7 clear days recorded; baseline unavailable.",
        )

    expected_kwh = round(baseline_yield_index * solar_energy_kwh_per_m2, 2)
    ratio = round(inverter_kwh / expected_kwh, 3) if expected_kwh > 0 else 0.0

    if ratio < 0.85:
        flag = PerformanceFlag.BELOW_EXPECTED
        explanation = f"Actual ({inverter_kwh:,.0f} kWh) is {ratio*100:.1f}% of expected ({expected_kwh:,.0f} kWh). Possible outage, soiling or curtailment."
    elif ratio > 1.15:
        flag = PerformanceFlag.CHECK_DATA
        explanation = f"Actual ({inverter_kwh:,.0f} kWh) is {ratio*100:.1f}% of expected ({expected_kwh:,.0f} kWh). Check data for meter or entry error."
    else:
        flag = PerformanceFlag.NORMAL
        explanation = f"Generation matches sunshine expectations ({ratio*100:.1f}% of expected {expected_kwh:,.0f} kWh)."

    return YieldInsight(
        report_date=report_date,
        inverter_kwh=inverter_kwh,
        solar_energy_kwh_per_m2=solar_energy_kwh_per_m2,
        yield_index=yield_idx,
        baseline_yield_index=baseline_yield_index,
        expected_kwh=expected_kwh,
        ratio_to_expected=ratio,
        flag=flag,
        is_clear_day=clear_day,
        explanation=explanation,
    )


def detect_weather_mismatch(
    plant_weather_text: Optional[str],
    auto_remark: Optional[str],
) -> Tuple[bool, str]:
    """Detect if plant-reported weather conflicts with weather service calculation.
    
    SPEC B7: If one says sunny and the other says overcast or rain, show a 'Weather mismatch' chip.
    """
    plant = (plant_weather_text or "").lower().strip()
    auto = (auto_remark or "").lower().strip()

    if not plant or not auto:
        return False, ""

    plant_is_sunny = any(w in plant for w in ["sunny", "clear"])
    plant_is_rain_overcast = any(w in plant for w in ["rain", "overcast", "drizzle", "cloudy"])

    auto_is_sunny = any(w in auto for w in ["sunny", "clear"])
    auto_is_rain_overcast = any(w in auto for w in ["rain", "overcast", "drizzle", "heavy rain", "light rain"])

    if plant_is_sunny and auto_is_rain_overcast:
        return True, f"Plant reports '{plant_weather_text}' but weather service reports '{auto_remark}'"
    if plant_is_rain_overcast and auto_is_sunny:
        return True, f"Plant reports '{plant_weather_text}' but weather service reports '{auto_remark}'"

    return False, ""
