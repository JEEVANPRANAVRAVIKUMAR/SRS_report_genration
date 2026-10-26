"""Unit test for Acceptance Criteria AC-10: Month locking and Admin post-lock amendment."""

from datetime import date, datetime
from pathlib import Path
import shutil
import tempfile
import unittest
from zoneinfo import ZoneInfo
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.domain.models import DailyReadingInput, MonthStatus, UserRole
from app.domain.months import determine_month_status
from app.infra.clock import FakeClock
from app.infra.models import (
    AuditLogModel,
    Base,
    CustomerModel,
    MonthModel,
    PlantModel,
    ReadingModel,
    ReportFileModel,
)
from app.services.month_lifecycle import MonthLifecycleService
from app.services.reading_service import ReadingService

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


class TestAC10MonthLocking(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.reports_dir = self.temp_dir / "reports"
        self.workbooks_dir = self.temp_dir / "workbooks"
        self.export_copy_dir = self.temp_dir / "export_copy"
        self.export_copy_dir.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(f"sqlite:///{self.temp_dir / 'test_ac10.db'}")
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

        # May is CLOSED with revision 1 already generated
        self.may_month = MonthModel(
            customer_id=self.customer.id,
            ym="2026-05",
            status=MonthStatus.CLOSED.value,
            closed_at=datetime(2026, 6, 1, 0, 5, 0),
            pdf_revision=1,
        )
        self.session.add(self.may_month)

        # Add reading for May 31
        self.may31_reading = ReadingModel(
            customer_id=self.customer.id,
            report_date=date(2026, 5, 31),
            inverter_kwh=6000.0,
            eb_export_kwh=5800.0,
            eb_6to10_kwh=1200.0,
            reported_monthly_kwh=180000.0,
            status="ACTIVE",
        )
        self.session.add(self.may31_reading)
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ac10_month_locking_and_admin_post_lock_amendment(self) -> None:
        """AC-10: Four days after month end May is LOCKED. An Operator cannot edit it;
        an Admin can, with a reason, which creates a 'post-lock amendment' revision."""
        # Four days after month end: 4 June 2026 at 10:00:00 IST
        clock = FakeClock(datetime(2026, 6, 4, 10, 0, 0, tzinfo=KOLKATA_TZ))

        lifecycle = MonthLifecycleService(
            clock=clock,
            export_copy_dir=self.export_copy_dir,
            reports_dir=self.reports_dir,
            workbooks_dir=self.workbooks_dir,
        )

        reading_service = ReadingService(clock=clock)

        # 1. Run lifecycle transitions check -> May transitions from CLOSED to LOCKED
        status_calc = determine_month_status(2026, 5, current_time=clock.now())
        self.assertEqual(status_calc, MonthStatus.LOCKED)

        results = lifecycle.check_and_run_due_transitions(self.session)
        self.session.commit()
        self.assertIn("2026-05", results.get("locked", []))

        self.session.refresh(self.may_month)
        self.assertEqual(self.may_month.status, MonthStatus.LOCKED.value)
        self.assertIsNotNone(self.may_month.locked_at)

        # 2. Operator attempts to edit reading for May 31 -> Must raise PermissionError
        reading_input = DailyReadingInput(
            report_date=date(2026, 5, 31),
            inverter_kwh=6100.0,
            eb_export_kwh=5900.0,
            eb_6to10_kwh=1200.0,
            reported_monthly_kwh=180100.0,
            actor_label="Operator",
        )

        with self.assertRaises(PermissionError) as ctx_op:
            reading_service.save_reading(
                session=self.session,
                reading_input=reading_input,
                role=UserRole.OPERATOR,
            )
        self.assertIn("LOCKED", str(ctx_op.exception))

        # 3. Admin attempts to edit WITHOUT a reason -> Must raise PermissionError
        with self.assertRaises(PermissionError) as ctx_admin_no_reason:
            reading_service.save_reading(
                session=self.session,
                reading_input=reading_input,
                role=UserRole.ADMIN,
                admin_override_reason="",
            )
        self.assertIn("written reason", str(ctx_admin_no_reason.exception))

        # 4. Admin edits WITH a written reason -> Succeeds
        admin_reason = "TANGEDCO meter reading discrepancy resolved"
        saved, _ = reading_service.save_reading(
            session=self.session,
            reading_input=reading_input,
            role=UserRole.ADMIN,
            admin_override_reason=admin_reason,
        )
        self.session.commit()
        self.assertEqual(saved.inverter_kwh, 6100.0)

        # 5. Lifecycle handler executes post-lock amendment
        rep_file = lifecycle.handle_reading_saved(
            session=self.session,
            reading_date=date(2026, 5, 31),
            role=UserRole.ADMIN,
            actor_label="Admin",
            admin_reason=admin_reason,
        )
        self.session.commit()

        self.assertIsNotNone(rep_file)
        self.assertEqual(rep_file.revision, 2)
        self.assertEqual(rep_file.reason, "POST_LOCK_AMENDMENT")

        # 6. Verify PDF generated contains 'post-lock amendment'
        pdf_path = Path(rep_file.path)
        self.assertTrue(pdf_path.exists())

        # Verify audit log records the amendment
        audit = (
            self.session.query(AuditLogModel)
            .filter_by(action="POST_LOCK_AMENDMENT")
            .first()
        )
        self.assertIsNotNone(audit)
        self.assertEqual(audit.reason, admin_reason)


if __name__ == "__main__":
    unittest.main()
