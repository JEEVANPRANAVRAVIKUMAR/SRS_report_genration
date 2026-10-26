"""Unit test for Acceptance Criteria AC-09: App not running on 1st and started on 3rd."""

from datetime import date, datetime
from pathlib import Path
import shutil
import tempfile
import unittest
from zoneinfo import ZoneInfo
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.domain.models import MonthStatus
from app.infra.clock import FakeClock
from app.infra.models import (
    AuditLogModel,
    Base,
    CustomerModel,
    JobRunModel,
    MonthModel,
    PlantModel,
    ReadingModel,
    ReportFileModel,
)
from app.services.month_lifecycle import MonthLifecycleService
from app.services.scheduler import SolarScheduler

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


class TestAC09CatchupStartup(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.reports_dir = self.temp_dir / "reports"
        self.workbooks_dir = self.temp_dir / "workbooks"

        self.engine = create_engine(f"sqlite:///{self.temp_dir / 'test_ac09.db'}")
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

        # May is still OPEN because the computer was off on June 1st
        self.may_month = MonthModel(
            customer_id=self.customer.id,
            ym="2026-05",
            status=MonthStatus.OPEN.value,
            pdf_revision=1,
        )
        self.session.add(self.may_month)

        # Add sample readings for May
        for d in range(1, 10):
            reading = ReadingModel(
                customer_id=self.customer.id,
                report_date=date(2026, 5, d),
                inverter_kwh=5500.0,
                eb_export_kwh=5300.0,
                eb_6to10_kwh=1100.0,
                reported_monthly_kwh=5500.0 * d,
                status="ACTIVE",
            )
            self.session.add(reading)

        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ac09_startup_catchup_late_close(self) -> None:
        """AC-09: App not running on the 1st and started on the 3rd: May is closed at start-up
        with a 'late close' audit entry."""
        # Simulated startup date: 3 June 2026 at 10:00:00 IST
        clock = FakeClock(datetime(2026, 6, 3, 10, 0, 0, tzinfo=KOLKATA_TZ))

        lifecycle = MonthLifecycleService(
            clock=clock,
            reports_dir=self.reports_dir,
            workbooks_dir=self.workbooks_dir,
        )

        scheduler = SolarScheduler(
            clock=clock,
            session_factory=self.SessionLocal,
            lifecycle_service=lifecycle,
        )

        # Execute start-up catchup routine
        results = scheduler.run_catchup_at_startup()

        self.assertIn("2026-05", results.get("closed", []), "May 2026 was not closed by startup catch-up")

        # 1. Verify May is now CLOSED
        self.session.refresh(self.may_month)
        self.assertEqual(self.may_month.status, MonthStatus.CLOSED.value)

        # 2. Verify PDF rev 1 was generated
        rep = (
            self.session.query(ReportFileModel)
            .filter_by(month_id=self.may_month.id, revision=1)
            .first()
        )
        self.assertIsNotNone(rep, "PDF rev 1 was not generated")
        self.assertTrue(Path(rep.path).exists())

        # 3. Verify 'late close' audit log entry exists
        audit_entries = (
            self.session.query(AuditLogModel)
            .filter_by(entity="months", entity_id="2026-05")
            .all()
        )
        self.assertTrue(len(audit_entries) >= 1)
        late_close_entry = next(
            (e for e in audit_entries if e.action == "LATE_CLOSE" or e.reason == "late close"),
            None,
        )
        self.assertIsNotNone(late_close_entry, "No audit log entry with 'late close' found!")
        self.assertEqual(late_close_entry.reason, "late close")

        # 4. Verify job_runs message records 'late close'
        job_run = (
            self.session.query(JobRunModel)
            .filter_by(job_name="MONTH_CLOSE", period="2026-05")
            .first()
        )
        self.assertIsNotNone(job_run)
        self.assertEqual(job_run.status, "SUCCESS")
        self.assertEqual(job_run.message, "late close")


if __name__ == "__main__":
    unittest.main()
