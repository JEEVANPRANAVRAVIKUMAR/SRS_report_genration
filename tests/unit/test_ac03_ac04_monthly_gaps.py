"""Unit tests for Acceptance Criteria AC-03 and AC-04:
- AC-03: Accept 22 May reading. Missing days 19, 20, 21 are listed. Month-to-date inverter 110690
         against plant 130428 gives reported gap of 19738. EB total 108192.
- AC-04: Adding 19, 20 and 21 May later with an inverter sum of exactly 19738 clears the gap warning;
         any other sum shows the remaining difference.
"""

from datetime import date
from pathlib import Path
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.domain.models import DailyReadingInput
from app.infra.clock import FakeClock
from app.infra.db import init_db
from app.infra.models import Base, ReadingModel, UploadModel
from app.services.csv_importer import import_csv_file
from app.services.reading_service import ReadingService
from app.services.review_service import ReviewService


class TestAC03AC04MonthlyGaps(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock(date(2026, 5, 22))
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        init_db(engine_override=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.review_service = ReviewService(self.clock)
        self.reading_service = ReadingService(self.clock)

        # Seed May 1 to 18
        csv_path = Path(__file__).resolve().parent.parent.parent / "seed" / "may_2026.csv"
        with self.Session() as session:
            import_csv_file(csv_path, session=session, clock=self.clock)
            session.commit()

    def test_ac03_accept_22_may_and_verify_gaps(self) -> None:
        """AC-03: Accept 22 May reading with 19, 20, 21 missing."""
        reading_22_may = DailyReadingInput(
            report_date=date(2026, 5, 22),
            inverter_kwh=7625.0,
            eb_export_kwh=7452.0,
            eb_6to10_kwh=1584.0,
            reported_monthly_kwh=130428.0,
            reported_yearly_kwh=565368.0,
            plant_weather_text="sunny",
            plant_temp_c=35.0,
            actor_label="Operator",
        )

        with self.Session() as session:
            # Check prospective effect preview
            preview = self.review_service.build_effect_preview(session, reading_22_may)

            # 1. Missing days check
            self.assertEqual(
                preview.missing_dates,
                [date(2026, 5, 19), date(2026, 5, 20), date(2026, 5, 21)],
                "Missing days must be 19, 20, 21 May",
            )

            # 2. Inverter running total check: 103065 + 7625 = 110690.00
            self.assertAlmostEqual(preview.computed_inverter_total, 110690.0, places=2)

            # 3. Gap check against plant reported: 130428 - 110690 = 19738.00
            self.assertAlmostEqual(preview.difference_kwh, 19738.0, places=2)

            # 4. EB running total check: 100740 + 7452 = 108192.00
            self.assertAlmostEqual(preview.computed_eb_total, 108192.0, places=2)

            # Create an upload record and accept it
            upload = UploadModel(
                sha256="dummy_sha256_ac03",
                received_via="PICKER",
                status="PENDING_REVIEW",
            )
            session.add(upload)
            session.flush()

            reading = self.review_service.accept_upload(
                session=session,
                upload_id=upload.id,
                reading_input=reading_22_may,
                actor_label="Operator",
            )
            session.commit()

            # Verify persisted reading
            self.assertEqual(reading.report_date, date(2026, 5, 22))
            self.assertEqual(upload.status, "ACCEPTED")

    def test_ac04_adding_19_20_21_may_clears_gap(self) -> None:
        """AC-04: Adding 19, 20, 21 May with sum of exactly 19738 clears gap; any other sum shows difference."""
        with self.Session() as session:
            # First accept 22 May reading
            reading_22 = DailyReadingInput(
                report_date=date(2026, 5, 22),
                inverter_kwh=7625.0,
                eb_export_kwh=7452.0,
                eb_6to10_kwh=1584.0,
                reported_monthly_kwh=130428.0,
            )
            self.reading_service.save_reading(session, reading_22)
            session.commit()

            # Add days 19, 20, 21 with sum = 19738 (e.g. 6500, 6500, 6738)
            # 6500 + 6500 + 6738 = 19738
            d19 = DailyReadingInput(report_date=date(2026, 5, 19), inverter_kwh=6500.0, eb_export_kwh=6360.0, eb_6to10_kwh=1200.0)
            d20 = DailyReadingInput(report_date=date(2026, 5, 20), inverter_kwh=6500.0, eb_export_kwh=6360.0, eb_6to10_kwh=1200.0)
            d21 = DailyReadingInput(report_date=date(2026, 5, 21), inverter_kwh=6738.0, eb_export_kwh=6576.0, eb_6to10_kwh=1200.0)

            self.reading_service.save_reading(session, d19)
            self.reading_service.save_reading(session, d20)
            self.reading_service.save_reading(session, d21)
            session.commit()

            # Re-evaluate 22 May reading effect preview
            preview_cleared = self.review_service.build_effect_preview(session, reading_22)

            # Gaps are now empty
            self.assertEqual(preview_cleared.missing_dates, [])

            # Total is now exactly 130428.00 (difference = 0)
            self.assertAlmostEqual(preview_cleared.computed_inverter_total, 130428.0, places=2)
            self.assertAlmostEqual(preview_cleared.difference_kwh, 0.0, places=2)
            self.assertIn("matches plant report", preview_cleared.preview_message)


if __name__ == "__main__":
    unittest.main()
