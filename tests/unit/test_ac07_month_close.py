"""Unit test for Acceptance Criteria AC-07: Month close at 00:05 IST on the 1st."""

from datetime import date, datetime
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.domain.models import DailyReadingInput, MonthStatus, UserRole
from app.infra.clock import FakeClock
from app.infra.models import (
    Base,
    CustomerModel,
    JobRunModel,
    MonthModel,
    NotificationModel,
    PlantModel,
    ReadingModel,
    ReportFileModel,
)
from app.services.month_lifecycle import MonthLifecycleService

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


class TestAC07MonthClose(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.reports_dir = self.temp_dir / "reports"
        self.workbooks_dir = self.temp_dir / "workbooks"
        self.export_copy_dir = self.temp_dir / "plant_export_copy"
        self.export_copy_dir.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(f"sqlite:///{self.temp_dir / 'test_ac07.db'}")
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.session = self.SessionLocal()

        # Seed plant and customer
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

        # Add sample readings for May 1-18
        for d in range(1, 19):
            reading = ReadingModel(
                customer_id=self.customer.id,
                report_date=date(2026, 5, d),
                inverter_kwh=5700.0,
                eb_export_kwh=5500.0,
                eb_6to10_kwh=1200.0,
                reported_monthly_kwh=5700.0 * d,
                status="ACTIVE",
            )
            self.session.add(reading)

        # Initial May Month record (OPEN)
        self.may_month = MonthModel(
            customer_id=self.customer.id,
            ym="2026-05",
            status=MonthStatus.OPEN.value,
            pdf_revision=1,
        )
        self.session.add(self.may_month)
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ac07_month_close_and_idempotency(self) -> None:
        """AC-07: Fake clock at 2026-06-01 00:05 IST: May becomes CLOSED, PDF rev 1 exists, June sheet exists.
        Running again changes nothing."""
        # 1. Fake clock at 2026-06-01 00:05:00 IST
        close_time = datetime(2026, 6, 1, 0, 5, 0, tzinfo=KOLKATA_TZ)
        clock = FakeClock(close_time)

        lifecycle = MonthLifecycleService(
            clock=clock,
            export_copy_dir=self.export_copy_dir,
            reports_dir=self.reports_dir,
            workbooks_dir=self.workbooks_dir,
        )

        # May is initially OPEN
        self.assertEqual(self.may_month.status, "OPEN")

        # 2. Run month close
        success, message = lifecycle.close_month(self.session, year=2026, month=5)
        self.session.commit()
        self.assertTrue(success, f"Close month failed: {message}")

        # 3. Assert May is now CLOSED
        self.session.refresh(self.may_month)
        self.assertEqual(self.may_month.status, MonthStatus.CLOSED.value)
        self.assertIsNotNone(self.may_month.closed_at)

        # 4. Assert PDF revision 1 exists on disk and in database
        report_files = (
            self.session.query(ReportFileModel)
            .filter_by(month_id=self.may_month.id, revision=1)
            .all()
        )
        self.assertEqual(len(report_files), 1)
        pdf_rec = report_files[0]
        self.assertEqual(pdf_rec.kind, "PDF")
        self.assertTrue(Path(pdf_rec.path).exists(), f"PDF does not exist at {pdf_rec.path}")
        self.assertEqual(len(pdf_rec.sha256), 64)

        # 5. Assert copied to EXPORT_COPY_DIR
        exported_pdf = self.export_copy_dir / Path(pdf_rec.path).name
        self.assertTrue(exported_pdf.exists(), f"PDF was not copied to EXPORT_COPY_DIR: {exported_pdf}")
        self.assertIsNotNone(pdf_rec.exported_to_folder_at)

        # 6. Assert June record exists with status OPEN
        june_month = (
            self.session.query(MonthModel)
            .filter_by(customer_id=self.customer.id, ym="2026-06")
            .first()
        )
        self.assertIsNotNone(june_month, "June 2026 MonthModel was not created.")
        self.assertEqual(june_month.status, MonthStatus.OPEN.value)

        # 7. Assert June sheet exists in Excel workbook
        wb_path = Path(self.may_month.workbook_path)
        self.assertTrue(wb_path.exists(), f"Workbook does not exist at {wb_path}")

        # Inspect sheet names inside OOXML workbook zip
        with zipfile.ZipFile(wb_path, "r") as z:
            workbook_xml = z.read("xl/workbook.xml").decode("utf-8")
            self.assertIn('name="MAY-2026"', workbook_xml)
            self.assertIn('name="JUN-2026"', workbook_xml)
            self.assertIn('name="Year Summary"', workbook_xml)

        # 8. Assert in-app notification exists
        notifs = self.session.query(NotificationModel).filter_by(ym="2026-05").all()
        self.assertTrue(any("May 2026 PDF ready" in n.title or "MAY-2026 PDF ready" in n.title for n in notifs))

        # 9. Assert job_runs recorded
        job_run = (
            self.session.query(JobRunModel)
            .filter_by(job_name="MONTH_CLOSE", period="2026-05")
            .first()
        )
        self.assertIsNotNone(job_run)
        self.assertEqual(job_run.status, "SUCCESS")

        # 10. IDEMPOTENCY: Run month close again
        succ_repeat, msg_repeat = lifecycle.close_month(self.session, year=2026, month=5)
        self.assertFalse(succ_repeat)
        self.assertIn("already closed", msg_repeat)

        # Verify no duplicate PDF rows or revised revision number
        count_reports = (
            self.session.query(ReportFileModel)
            .filter_by(month_id=self.may_month.id)
            .count()
        )
        self.assertEqual(count_reports, 1)
        self.assertEqual(self.may_month.pdf_revision, 1)

    def test_admin_controls_close_reopen_and_regenerate(self) -> None:
        """Verify Admin controls: Close month now, Reopen month (reason required), Regenerate PDF."""
        clock = FakeClock(datetime(2026, 5, 20, 10, 0, 0, tzinfo=KOLKATA_TZ))
        lifecycle = MonthLifecycleService(
            clock=clock,
            export_copy_dir=self.export_copy_dir,
            reports_dir=self.reports_dir,
            workbooks_dir=self.workbooks_dir,
        )

        # 1. Admin close now before month end
        succ, msg = lifecycle.admin_close_now(self.session, 2026, 5, actor_label="Admin", reason="Early audit close")
        self.session.commit()
        self.assertTrue(succ)
        self.session.refresh(self.may_month)
        self.assertEqual(self.may_month.status, MonthStatus.CLOSED.value)

        # 2. Reopen without reason must fail
        with self.assertRaises(ValueError) as ctx:
            lifecycle.admin_reopen_month(self.session, 2026, 5, actor_label="Admin", reason="")
        self.assertIn("reason", str(ctx.exception).lower())

        # 3. Reopen with written reason succeeds
        succ, msg = lifecycle.admin_reopen_month(
            self.session, 2026, 5, actor_label="Admin", reason="Reopening for late incoming bill figures"
        )
        self.session.commit()
        self.assertTrue(succ)
        self.session.refresh(self.may_month)
        self.assertEqual(self.may_month.status, MonthStatus.OPEN.value)

        # 4. Regenerate PDF
        rep = lifecycle.admin_regenerate_pdf(self.session, 2026, 5, actor_label="Admin", reason="Regenerate test")
        self.session.commit()
        self.assertIsNotNone(rep)
        self.assertTrue(Path(rep.path).exists())


if __name__ == "__main__":
    unittest.main()
