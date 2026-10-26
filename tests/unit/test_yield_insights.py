"""Unit tests for Yield Index, baseline logic, performance flags, and weather mismatch detection (SPEC B7)."""

from datetime import date
import unittest
from app.domain.insights import (
    calculate_yield_baseline,
    compute_yield_index,
    detect_weather_mismatch,
    evaluate_performance_insight,
    is_clear_day,
)
from app.domain.weather_models import PerformanceFlag


class TestYieldInsights(unittest.TestCase):
    def test_yield_index_calculation(self) -> None:
        """yield_index = inverter kWh divided by solar energy in kWh/m2."""
        # 7625 kWh / 6.1 kWh/m2 = 1250.0
        y_idx = compute_yield_index(inverter_kwh=7625.0, solar_energy_kwh_per_m2=6.1)
        self.assertEqual(y_idx, 1250.0)

        # Zero solar energy returns 0.0 without division by zero
        self.assertEqual(compute_yield_index(7625.0, 0.0), 0.0)

    def test_clear_day_definition(self) -> None:
        """Clear day requires cloud under 30% and no rain (< 0.1 mm)."""
        self.assertTrue(is_clear_day(mean_daytime_cloud_pct=25.0, rain_24h_mm=0.0))
        self.assertFalse(is_clear_day(mean_daytime_cloud_pct=30.0, rain_24h_mm=0.0))  # not strictly under 30%
        self.assertFalse(is_clear_day(mean_daytime_cloud_pct=15.0, rain_24h_mm=0.5))  # has rain

    def test_baseline_requires_at_least_7_clear_days(self) -> None:
        """Baseline is the median of clear days, but ONLY when at least 7 such days exist."""
        # 6 days: returns None
        six_days = [1200.0, 1220.0, 1240.0, 1260.0, 1280.0, 1300.0]
        self.assertIsNone(calculate_yield_baseline(six_days))

        # 7 days: returns median (1250.0)
        seven_days = [1200.0, 1220.0, 1240.0, 1250.0, 1260.0, 1280.0, 1300.0]
        self.assertEqual(calculate_yield_baseline(seven_days), 1250.0)

    def test_performance_flags(self) -> None:
        """Flag 'Below expected' when < 85%, 'Check data' when > 115%, otherwise normal."""
        report_date = date(2026, 5, 22)
        baseline = 1250.0
        solar = 6.0  # expected = 1250 * 6.0 = 7500.0 kWh

        # 1. Below expected: 6000 kWh / 7500 kWh = 80.0% < 85%
        res_low = evaluate_performance_insight(
            report_date=report_date,
            inverter_kwh=6000.0,
            solar_energy_kwh_per_m2=solar,
            mean_daytime_cloud_pct=10.0,
            rain_24h_mm=0.0,
            baseline_yield_index=baseline,
        )
        self.assertEqual(res_low.flag, PerformanceFlag.BELOW_EXPECTED)
        self.assertIn("Below expected for the sunshine", res_low.flag.value)

        # 2. Check data: 9000 kWh / 7500 kWh = 120.0% > 115%
        res_high = evaluate_performance_insight(
            report_date=report_date,
            inverter_kwh=9000.0,
            solar_energy_kwh_per_m2=solar,
            mean_daytime_cloud_pct=10.0,
            rain_24h_mm=0.0,
            baseline_yield_index=baseline,
        )
        self.assertEqual(res_high.flag, PerformanceFlag.CHECK_DATA)
        self.assertIn("Check data", res_high.flag.value)

        # 3. Normal: 7400 kWh / 7500 kWh = 98.7%
        res_norm = evaluate_performance_insight(
            report_date=report_date,
            inverter_kwh=7400.0,
            solar_energy_kwh_per_m2=solar,
            mean_daytime_cloud_pct=10.0,
            rain_24h_mm=0.0,
            baseline_yield_index=baseline,
        )
        self.assertEqual(res_norm.flag, PerformanceFlag.NORMAL)

    def test_weather_mismatch_detection(self) -> None:
        """Weather mismatch chip appears when sunny conflicts with overcast/rain."""
        # Mismatch: Plant says sunny, auto says overcast/rain
        mismatch, reason = detect_weather_mismatch(
            plant_weather_text="sunny",
            auto_remark="Overcast, rain 14 mm, 29°C",
        )
        self.assertTrue(mismatch)
        self.assertIn("sunny", reason)

        # Mismatch: Plant says rain, auto says sunny
        mismatch2, reason2 = detect_weather_mismatch(
            plant_weather_text="rain",
            auto_remark="Sunny, 35°C",
        )
        self.assertTrue(mismatch2)

        # No mismatch: both indicate sunny
        mismatch3, _ = detect_weather_mismatch(
            plant_weather_text="sunny",
            auto_remark="Sunny, 35°C",
        )
        self.assertFalse(mismatch3)


if __name__ == "__main__":
    unittest.main()
