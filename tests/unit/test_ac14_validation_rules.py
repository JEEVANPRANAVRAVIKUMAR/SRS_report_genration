"""Unit tests for Acceptance Criteria AC-14:
Each rule in B6 has a passing and a failing test, including 8 May 6am-10am = 1376 raising the multiple-of-12 warning.
"""

from datetime import date
import unittest
from app.domain.models import DailyReadingInput, RuleSeverity
from app.domain.validation import validate_reading


class TestAC14ValidationRules(unittest.TestCase):
    def base_valid_reading(self) -> DailyReadingInput:
        return DailyReadingInput(
            report_date=date(2026, 5, 1),
            inverter_kwh=6489.0,
            eb_export_kwh=6336.0,  # 6336 / 6489 = 0.9764 (in [0.95, 1.00]), 6336 % 12 == 0
            eb_6to10_kwh=1236.0,   # 1236 % 12 == 0
            reported_monthly_kwh=6489.0,
            reported_yearly_kwh=500000.0,
            inverter_availability_pct=100.0,
            grid_availability_pct=100.0,
            fault_text="",
            plant_weather_text="sunny",
            plant_temp_c=35.0,
        )

    # Rule 1: Mandatory fields present (Error)
    def test_rule1_passing(self) -> None:
        r = self.base_valid_reading()
        res = validate_reading(r)
        self.assertNotIn(1, [f.rule_number for f in res.errors])

    def test_rule1_failing(self) -> None:
        r = self.base_valid_reading()
        r.inverter_kwh = None
        res = validate_reading(r)
        self.assertIn(1, [f.rule_number for f in res.errors])
        self.assertFalse(res.is_valid)

    # Rule 2: Non-negative numbers (Error)
    def test_rule2_passing(self) -> None:
        r = self.base_valid_reading()
        res = validate_reading(r)
        self.assertNotIn(2, [f.rule_number for f in res.errors])

    def test_rule2_failing(self) -> None:
        r = self.base_valid_reading()
        r.inverter_kwh = -100.0
        res = validate_reading(r)
        self.assertIn(2, [f.rule_number for f in res.errors])
        self.assertFalse(res.is_valid)

    # Rule 3: EB export not above inverter (Error, admin override with reason)
    def test_rule3_passing(self) -> None:
        r = self.base_valid_reading()
        r.inverter_kwh = 7000.0
        r.eb_export_kwh = 6840.0
        res = validate_reading(r)
        self.assertNotIn(3, [f.rule_number for f in res.errors])

    def test_rule3_failing_and_override(self) -> None:
        r = self.base_valid_reading()
        r.inverter_kwh = 7000.0
        r.eb_export_kwh = 7200.0  # EB > Inverter!
        res = validate_reading(r)
        self.assertIn(3, [f.rule_number for f in res.errors])
        self.assertFalse(res.can_accept(is_admin=False))
        # Admin can override with reason
        self.assertTrue(res.can_accept(is_admin=True, admin_override_reason="Auxiliary supply verified"))

    # Rule 4: EB / Inverter ratio in [0.95, 1.00] (Warning)
    def test_rule4_passing(self) -> None:
        r = self.base_valid_reading()  # ratio = 6336 / 6489 = 0.976
        res = validate_reading(r)
        self.assertNotIn(4, [f.rule_number for f in res.warnings])

    def test_rule4_failing(self) -> None:
        r = self.base_valid_reading()
        r.inverter_kwh = 7000.0
        r.eb_export_kwh = 6300.0  # ratio = 0.90 < 0.95
        res = validate_reading(r)
        self.assertIn(4, [f.rule_number for f in res.warnings])

    # Rule 5: EB and 6am-10am multiples of EB_MF (default 12) (Warning)
    def test_rule5_passing(self) -> None:
        r = self.base_valid_reading()  # 6336 % 12 == 0, 1236 % 12 == 0
        res = validate_reading(r)
        self.assertNotIn(5, [f.rule_number for f in res.warnings])

    def test_rule5_failing_may_8_seed_data(self) -> None:
        """AC-14 explicitly specifies: 8 May 6am-10am = 1376 raising multiple-of-12 warning."""
        r = self.base_valid_reading()
        r.report_date = date(2026, 5, 8)
        r.inverter_kwh = 5765.0
        r.eb_export_kwh = 5640.0   # 5640 / 12 = 470 (exact)
        r.eb_6to10_kwh = 1376.0    # 1376 / 12 = 114.666... (not divisible by 12!)
        res = validate_reading(r, eb_mf=12)
        r5_warnings = [f for f in res.warnings if f.rule_number == 5]
        self.assertTrue(len(r5_warnings) > 0, "Expected Rule 5 warning for 1376 not multiple of 12")
        self.assertIn("1376", r5_warnings[0].message)

    # Rule 6: 6am-10am not above EB export (Error)
    def test_rule6_passing(self) -> None:
        r = self.base_valid_reading()
        r.eb_6to10_kwh = 1500.0
        r.eb_export_kwh = 6000.0
        res = validate_reading(r)
        self.assertNotIn(6, [f.rule_number for f in res.errors])

    def test_rule6_failing(self) -> None:
        r = self.base_valid_reading()
        r.eb_export_kwh = 1000.0
        r.eb_6to10_kwh = 1500.0  # 6am-10am exceeds full day EB!
        res = validate_reading(r)
        self.assertIn(6, [f.rule_number for f in res.errors])

    # Rule 7: Inverter <= 12,000 kWh (Error); spike > 1.3x 60-day max (Warning)
    def test_rule7_passing(self) -> None:
        r = self.base_valid_reading()
        res = validate_reading(r, max_daily_inverter_kwh=12000.0, best_inverter_last_60_days=7000.0)
        self.assertNotIn(7, [f.rule_number for f in res.errors])
        self.assertNotIn(7, [f.rule_number for f in res.warnings])

    def test_rule7_failing_error(self) -> None:
        r = self.base_valid_reading()
        r.inverter_kwh = 12500.0  # exceeds 12000
        res = validate_reading(r, max_daily_inverter_kwh=12000.0)
        self.assertIn(7, [f.rule_number for f in res.errors])

    def test_rule7_failing_warning_spike(self) -> None:
        r = self.base_valid_reading()
        r.inverter_kwh = 9500.0
        # 60-day best is 6000; 1.3 * 6000 = 7800 < 9500
        res = validate_reading(r, best_inverter_last_60_days=6000.0, inverter_spike_ratio=1.3)
        self.assertIn(7, [f.rule_number for f in res.warnings])

    # Rule 8: Zero generation or zero export (Warning)
    def test_rule8_passing(self) -> None:
        r = self.base_valid_reading()
        res = validate_reading(r)
        self.assertNotIn(8, [f.rule_number for f in res.warnings])

    def test_rule8_failing(self) -> None:
        r = self.base_valid_reading()
        r.inverter_kwh = 0.0
        res = validate_reading(r)
        self.assertIn(8, [f.rule_number for f in res.warnings])

    # Rule 9: Computed MTD vs reported monthly
    def test_rule9_passing(self) -> None:
        r = self.base_valid_reading()
        r.reported_monthly_kwh = 10000.0
        res = validate_reading(r, computed_month_to_date_inverter=10000.5)
        self.assertNotIn(9, [f.rule_number for f in res.findings])

    def test_rule9_failing_plant_higher(self) -> None:
        r = self.base_valid_reading()
        r.reported_monthly_kwh = 15000.0
        # Plant reports 15000, computed is 10000 -> gap of 5000 (missing days)
        res = validate_reading(r, computed_month_to_date_inverter=10000.0)
        r9_infos = [f for f in res.infos if f.rule_number == 9]
        self.assertTrue(len(r9_infos) > 0)
        self.assertIn("missing days", r9_infos[0].message)

    def test_rule9_failing_computed_higher(self) -> None:
        r = self.base_valid_reading()
        r.reported_monthly_kwh = 10000.0
        # Computed 12000 > Plant 10000 -> possible duplicate or wrong digit
        res = validate_reading(r, computed_month_to_date_inverter=12000.0)
        r9_warns = [f for f in res.warnings if f.rule_number == 9]
        self.assertTrue(len(r9_warns) > 0)
        self.assertIn("possible duplicate", r9_warns[0].message)

    # Rule 10: Availability < 100% or fault text (Warning)
    def test_rule10_passing(self) -> None:
        r = self.base_valid_reading()
        res = validate_reading(r)
        self.assertNotIn(10, [f.rule_number for f in res.warnings])

    def test_rule10_failing(self) -> None:
        r = self.base_valid_reading()
        r.inverter_availability_pct = 95.0
        r.fault_text = "Grid trip at 14:00"
        res = validate_reading(r)
        self.assertIn(10, [f.rule_number for f in res.warnings])

    # Rule 11: Gaps between recorded dates (Info)
    def test_rule11_passing(self) -> None:
        r = self.base_valid_reading()
        res = validate_reading(r, missing_dates_in_month=[])
        self.assertNotIn(11, [f.rule_number for f in res.findings])

    def test_rule11_failing(self) -> None:
        r = self.base_valid_reading()
        res = validate_reading(r, missing_dates_in_month=[date(2026, 5, 2), date(2026, 5, 3)])
        self.assertIn(11, [f.rule_number for f in res.infos])

    # Rule 12: Plant temp vs weather service temp > 6°C (Info)
    def test_rule12_passing(self) -> None:
        r = self.base_valid_reading()
        r.plant_temp_c = 35.0
        res = validate_reading(r, weather_service_temp_c=33.0)
        self.assertNotIn(12, [f.rule_number for f in res.findings])

    def test_rule12_failing(self) -> None:
        r = self.base_valid_reading()
        r.plant_temp_c = 35.0
        res = validate_reading(r, weather_service_temp_c=26.0)  # diff = 9°C > 6°C
        self.assertIn(12, [f.rule_number for f in res.infos])


if __name__ == "__main__":
    unittest.main()
