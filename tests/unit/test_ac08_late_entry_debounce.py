"""Unit test for Acceptance Criteria AC-08: Late entry during grace period with debounce."""

from datetime import date, datetime
from pathlib import Path
import shutil
import tempfile
import unittest
from zoneinfo import ZoneInfo
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.domain.models import DailyReadingInput, EntryMethod, MonthStatus, UserRole
from app.infra.clock import FakeClock
from app.infra.models import (
    Base,
    CustomerModel,
    MonthModel,
    NotificationModel,
    PlantModel,
    ReadingModel,
    ReportFileModel,
    UploadModel,
)
from app.services.month_lifecycle import MonthLifecycleService
from app.services.review_service import ReviewService

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


class TestAC08LateEntryDebounce(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.reports_dir = self.temp_dir / "reports"
        self.workbooks_dir = self.temp_dir / "workbooks"
        self.export_copy_dir = self.temp_dir / "plant_export_copy"
        self.export_copy_dir.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(f"sqlite:///{self.temp_dir / 'test_ac08.db'}")
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

        # May is CLOSED with revision 1 already generated
        self.may_month = MonthModel(
            customer_id=self.customer.id,
            ym="2026-05",
            status=MonthStatus.CLOSED.value,
            closed_at=datetime(2026, 6, 1, 0, 5, 0),
            pdf_revision=1,
        )
        self.session.add(self.may_month)

        # June is OPEN
        self.june_month = MonthModel(
            customer_id=self.customer.id,
            ym="2026-06",
            status=MonthStatus.OPEN.value,
            pdf_revision=1,
        )
        self.session.add(self.june_month)
        self.session.commit()

        # Create rev 1 report file record
        self.rep1 = ReportFileModel(
            month_id=self.may_month.id,
            kind="PDF",
            revision=1,
            path=str(self.reports_dir / "2026" / "SRS_Kumaran_Generation_2026-05_rev1.pdf"),
            sha256="dummy_sha256_rev1",
            created_at=datetime(2026, 6, 1, 0, 5, 0),
            reason="CLOSE",
        )
        self.session.add(self.rep1)
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ac08_late_entry_debounce_issues_revision_2(self) -> None:
        """AC-08: Upload for 31 May on 1 June at 09:00 goes into May, issues PDF revision 2 after debounce,
        and nothing goes into June."""
        # Clock at 1 June 2026 09:00:00 IST
        clock = FakeClock(datetime(2026, 6, 1, 9, 0, 0, tzinfo=KOLKATA_TZ))

        lifecycle = MonthLifecycleService(
            clock=clock,
            export_copy_dir=self.export_copy_dir,
            debounce_seconds=120.0,
            reports_dir=self.reports_dir,
            workbooks_dir=self.workbooks_dir,
        )

        # Create upload for 31 May
        upload = UploadModel(
            sha256="sample_hash_31may",
            received_via="CAMERA",
            status="PENDING_REVIEW",
        )
        self.session.add(upload)
        self.session.commit()

        review_service = ReviewService(clock=clock)
        review_service.month_lifecycle = lifecycle

        # Reading input for 31 May 2026
        reading_input = DailyReadingInput(
            report_date=date(2026, 5, 31),
            inverter_kwh=6250.0,
            eb_export_kwh=6120.0,
            eb_6to10_kwh=1400.0,
            reported_monthly_kwh=180000.0,
            manual_remark="Month end final reading",
            auto_remark="Sunny, 35°C",
        )

        # Operator accepts the reading on 1 June at 09:00
        saved_reading = review_service.accept_upload(
            session=self.session,
            upload_id=upload.id,
            reading_input=reading_input,
            actor_label="Operator",
            role=UserRole.OPERATOR,
        )
        self.session.commit()

        # 1. Assert reading belongs to May
        self.assertEqual(saved_reading.report_date, date(2026, 5, 31))
        may_readings = (
            self.session.query(ReadingModel)
            .filter(ReadingModel.report_date == date(2026, 5, 31))
            .all()
        )
        self.assertEqual(len(may_readings), 1)

        # 2. Assert nothing went into June
        june_readings = (
            self.session.query(ReadingModel)
            .filter(
                ReadingModel.report_date >= date(2026, 6, 1),
                ReadingModel.report_date <= date(2026, 6, 30),
            )
            .all()
        )
        self.assertEqual(len(june_readings), 0, "Readings improperly inserted into June!")

        # 3. Assert debounce queue has the change
        self.assertTrue(lifecycle.debounce_service.has_pending("2026-05"))
        self.assertIn(date(2026, 5, 31), lifecycle.debounce_service.get_pending_dates("2026-05"))

        # 4. Debounce flush (simulating expiry of the 2-minute timer)
        reps = lifecycle.debounce_service.flush(self.session, ym="2026-05")
        self.session.commit()
        self.assertEqual(len(reps), 1)
        rev2_rep = reps[0]

        # 5. Assert PDF revision 2 exists
        self.assertEqual(rev2_rep.revision, 2)
        self.assertEqual(rev2_rep.reason, "LATE_ENTRY")
        self.assertTrue(Path(rev2_rep.path).exists())
        self.assertIn("_rev2.pdf", rev2_rep.path)

        # Assert MonthModel updated to rev 2
        self.session.refresh(self.may_month)
        self.assertEqual(self.may_month.pdf_revision, 2)

        # 6. Assert copied to EXPORT_COPY_DIR
        exported_copy = self.export_copy_dir / Path(rev2_rep.path).name
        self.assertTrue(exported_copy.exists())
        self.assertIsNotNone(rev2_rep.exported_to_folder_at)

        # 7. Assert notification dispatch: 'revision 2: 31 May added'
        notifs = (
            self.session.query(NotificationModel)
            .filter_by(ym="2026-05", kind="REVISION_ADDED")
            .all()
        )
        self.assertTrue(len(notifs) >= 1)
        self.assertIn("revision 2: 31 May added", notifs[-1].message)


if __name__ == "__main__":
    unittest.main()
