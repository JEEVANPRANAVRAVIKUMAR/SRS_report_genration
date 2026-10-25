"""Unit test for Acceptance Criteria AC-01:
Extraction on the sample image: report date 2026-05-22; SRS row; serial 5; 1 MW;
inverter 7625; monthly 130428; yearly 565368; EB 7452; 6am-10am 1584;
availability 100 and 100; weather 'sunny'; temperature 35.
It must NOT return the Prabhu Textiles row (7640, 7476, 1608).
"""

from datetime import date
from pathlib import Path
import unittest
from app.infra.clock import FakeClock
from app.services.extraction.post_processing import post_process_extraction
from app.services.extraction.provider import FakeGeminiExtractionProvider


class TestAC01Extraction(unittest.TestCase):
    def setUp(self) -> None:
        # Clock set to 2026-05-22
        self.clock = FakeClock(date(2026, 5, 22))
        self.image_path = Path(__file__).resolve().parent.parent.parent / "tests" / "golden" / "report_2026-05-22.jpeg"
        self.assertTrue(self.image_path.exists(), f"Golden sample image not found at {self.image_path}")

    def test_extraction_on_sample_image(self) -> None:
        provider = FakeGeminiExtractionProvider()
        raw_output = provider.extract(self.image_path)

        # Post-process and normalize
        result = post_process_extraction(raw_output, clock=self.clock)

        # 1. Date verification
        self.assertEqual(result.date_raw.value, "22/05/2026")
        self.assertEqual(result.date_iso.value, "2026-05-22")

        # 2. SRS Row verification (Serial 5, 1 MW)
        self.assertEqual(result.serial_no.value, 5)
        self.assertEqual(result.capacity_mw.value, 1.0)
        self.assertEqual(result.inverter_kwh.value, 7625.00)
        self.assertEqual(result.reported_monthly_kwh.value, 130428.00)
        self.assertEqual(result.reported_yearly_kwh.value, 565368.00)
        self.assertEqual(result.eb_export_kwh.value, 7452.00)
        self.assertEqual(result.eb_6to10_kwh.value, 1584.00)
        self.assertEqual(result.inverter_availability_pct.value, 100.0)
        self.assertEqual(result.grid_availability_pct.value, 100.0)
        self.assertEqual(result.plant_weather_text.value, "sunny")
        self.assertEqual(result.plant_temp_c.value, 35.0)

        # 3. Non-negotiable AC-01 check: Must NOT return Prabhu Textiles row (serial 6, 7640, 7476, 1608)
        self.assertNotEqual(result.serial_no.value, 6, "Must not return Prabhu Textiles row!")
        self.assertNotEqual(result.inverter_kwh.value, 7640.00, "Inverter must not be Prabhu Textiles (7640)")
        self.assertNotEqual(result.eb_export_kwh.value, 7476.00, "EB must not be Prabhu Textiles (7476)")
        self.assertNotEqual(result.eb_6to10_kwh.value, 1608.00, "6-10am must not be Prabhu Textiles (1608)")


if __name__ == "__main__":
    unittest.main()
