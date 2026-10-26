"""Unit test for Acceptance Criteria AC-11: Server clock in UTC timezone."""

from datetime import date, datetime, timezone
from pathlib import Path
import shutil
import tempfile
import unittest
from zoneinfo import ZoneInfo
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.domain.models import MonthStatus
from app.domain.months import determine_month_status, get_month_close_datetime
from app.infra.clock import FakeClock
from app.infra.models import (
    Base,
    CustomerModel,
    JobRunModel,
    MonthModel,
    PlantModel,
    ReadingModel,
    ReportFileModel,
)
from app.services.month_lifecycle import MonthLifecycleService

UTC_TZ = timezone.utc
KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


class TestAC11UTCClockClose(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.reports_dir = self.temp_dir / "reports"
        self.workbooks_dir = self.temp_dir / "workbooks"

        self.engine = create_engine(f"sqlite:///{self.temp_dir / 'test_ac11.db'}")
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.session = self.SessionLocal()

        self.plant = PlantModel(
            name="Sunpro Antichettipalayam",
            latitude=10.851319,
            longitude=77.909541,
            timezone="Asia/Kolkata",
            capacity_mw=10.0,
        )
        self.session.add(self.plant)
        self.session.flush()

        self.customer = CustomerModel(
            plant_id=self.plant.id,
            display_name="M/s. SRS KUMARAN INDIA PVT LTD",
            aliases="[]",
            capacity_mw=1.0,
            is_target=True,
        )
        self.session.add(self.customer)
        self.session.flush()

        # May is OPEN
        self.may_month = MonthModel(
            customer_id=self.customer.id,
            ym="2026-05",
            status=MonthStatus.OPEN.value,
            pdf_revision=1,
        )
        self.session.add(self.may_month)

        # Seed sample reading
        reading = ReadingModel(
            customer_id=self.customer.id,
            report_date=date(2026, 5, 1),
            inverter_kwh=5800.0,
            eb_export_kwh=5600.0,
            eb_6to10_kwh=1200.0,
            reported_monthly_kwh=5800.0,
            status="ACTIVE",
        )
        self.session.add(reading)
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ac11_utc_clock_triggers_close_accurately(self) -> None:
        """AC-11: Server timezone UTC: 18:35 UTC on 31 May triggers the close; 18:20 UTC does not."""
        # 1. Test 18:20 UTC on 31 May (23:50 IST on 31 May)
        utc_1820 = datetime(2026, 5, 31, 18, 20, 0, tzinfo=UTC_TZ)
        clock_1820 = FakeClock(utc_1820)

        # Verify pure domain month status determination
        status_1820 = determine_month_status(2026, 5, current_time=clock_1820.now())
        self.assertEqual(status_1820, MonthStatus.OPEN, "18:20 UTC incorrectly triggered month close!")

        lifecycle_1820 = MonthLifecycleService(
            clock=clock_1820,
            reports_dir=self.reports_dir,
            workbooks_dir=self.workbooks_dir,
        )

        results_1820 = lifecycle_1820.check_and_run_due_transitions(self.session)
        self.session.commit()

        self.assertNotIn("2026-05", results_1820.get("closed", []))
        self.session.refresh(self.may_month)
        self.assertEqual(self.may_month.status, MonthStatus.OPEN.value, "May must remain OPEN at 18:20 UTC")

        # No PDF rev 1 should exist
        rep_1820 = (
            self.session.query(ReportFileModel)
            .filter_by(month_id=self.may_month.id)
            .first()
        )
        self.assertIsNone(rep_1820)

        # 2. Test 18:35 UTC on 31 May (00:05 IST on 1 June)
        utc_1835 = datetime(2026, 5, 31, 18, 35, 0, tzinfo=UTC_TZ)
        clock_1835 = FakeClock(utc_1835)

        # Verify pure domain month status determination
        status_1835 = determine_month_status(2026, 5, current_time=clock_1835.now())
        self.assertEqual(status_1835, MonthStatus.CLOSED, "18:35 UTC failed to trigger month close!")

        lifecycle_1835 = MonthLifecycleService(
            clock=clock_1835,
            reports_dir=self.reports_dir,
            workbooks_dir=self.workbooks_dir,
        )

        results_1835 = lifecycle_1835.check_and_run_due_transitions(self.session)
        self.session.commit()

        self.assertIn("2026-05", results_1835.get("closed", []))
        self.session.refresh(self.may_month)
        self.assertEqual(self.may_month.status, MonthStatus.CLOSED.value, "May must be CLOSED at 18:35 UTC")

        # PDF rev 1 should now exist
        rep_1835 = (
            self.session.query(ReportFileModel)
            .filter_by(month_id=self.may_month.id, revision=1)
            .first()
        )
        self.assertIsNotNone(rep_1835)
        self.assertTrue(Path(rep_1835.path).exists())

        # job_runs should record success
        job_run = (
            self.session.query(JobRunModel)
            .filter_by(job_name="MONTH_CLOSE", period="2026-05")
            .first()
        )
        self.assertIsNotNone(job_run)
        self.assertEqual(job_run.status, "SUCCESS")


if __name__ == "__main__":
    unittest.main()
