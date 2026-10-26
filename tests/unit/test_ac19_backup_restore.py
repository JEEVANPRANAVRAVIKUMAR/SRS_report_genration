"""Unit test for Acceptance Criteria AC-19: Backup and restore round trip reproducibility."""

from datetime import date, datetime
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
import sqlite3
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.domain.models import DailyReadingInput, MonthStatus
from app.infra.clock import FakeClock
from app.infra.models import Base, CustomerModel, MonthModel, PlantModel, ReadingModel, ReportFileModel
from app.services.backup import BackupService
from app.services.reports.excel import ExcelReportGenerator
from app.services.reports.pdf import PDFReportGenerator


class TestAC19BackupRestore(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db_path = self.temp_dir / "live" / "srs_solar.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.workbooks_dir = self.temp_dir / "live" / "workbooks"
        self.reports_dir = self.temp_dir / "live" / "reports"
        self.backups_dir = self.temp_dir / "backups"

        self.engine = create_engine(f"sqlite:///{self.db_path}")
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.session = self.SessionLocal()

        self.clock = FakeClock(datetime(2026, 6, 1, 0, 5, 0))

        # Seed plant & customer
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

        # Add readings for May 1-5
        readings_input = []
        for d in range(1, 6):
            r = ReadingModel(
                customer_id=self.customer.id,
                report_date=date(2026, 5, d),
                inverter_kwh=6000.0,
                eb_export_kwh=5850.0,
                eb_6to10_kwh=1250.0,
                reported_monthly_kwh=6000.0 * d,
                status="ACTIVE",
            )
            self.session.add(r)
            readings_input.append(
                DailyReadingInput(
                    report_date=date(2026, 5, d),
                    inverter_kwh=6000.0,
                    eb_export_kwh=5850.0,
                    eb_6to10_kwh=1250.0,
                )
            )

        self.session.commit()

        # Generate live reports
        pdf_gen = PDFReportGenerator(output_dir=self.reports_dir)
        self.pdf_file = pdf_gen.generate_monthly_pdf(
            year=2026,
            month=5,
            readings=readings_input,
            clock=self.clock,
            revision=1,
        )

        excel_gen = ExcelReportGenerator(output_dir=self.workbooks_dir)
        self.excel_file = excel_gen.generate_annual_workbook(
            year=2026,
            readings_by_month={5: readings_input},
            month_statuses={5: MonthStatus.CLOSED},
            month_revisions={5: 1},
        )

        # Compute original hashes
        self.orig_pdf_hash = hashlib.sha256(self.pdf_file.read_bytes()).hexdigest()
        self.orig_excel_hash = hashlib.sha256(self.excel_file.read_bytes()).hexdigest()

        # Record in report_files
        month_rec = MonthModel(
            customer_id=self.customer.id,
            ym="2026-05",
            status=MonthStatus.CLOSED.value,
            pdf_revision=1,
            workbook_path=str(self.excel_file),
        )
        self.session.add(month_rec)
        self.session.flush()

        rep_rec = ReportFileModel(
            month_id=month_rec.id,
            kind="PDF",
            revision=1,
            path=str(self.pdf_file),
            sha256=self.orig_pdf_hash,
            reason="CLOSE",
        )
        self.session.add(rep_rec)
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ac19_backup_and_restore_round_trip_reproduces_identical_hashes(self) -> None:
        """AC-19: A backup and restore round trip reproduces identical workbooks and PDF hashes."""
        backup_service = BackupService(
            clock=self.clock,
            backups_dir=self.backups_dir,
            workbooks_dir=self.workbooks_dir,
            reports_dir=self.reports_dir,
        )

        # 1. Create consistent backup
        backup_dir = backup_service.create_backup(
            session=self.session,
            engine=self.engine,
            label="nightly_backup",
            actor_label="System",
        )
        self.assertTrue(backup_dir.exists())
        self.assertTrue((backup_dir / "manifest.json").exists())
        self.assertTrue((backup_dir / "srs_solar.db").exists())

        # 2. Simulate complete data loss by restoring into an empty target directory
        restore_dir = self.temp_dir / "restored_system"
        restore_db = restore_dir / "srs_solar.db"
        restore_wb_dir = restore_dir / "workbooks"
        restore_rep_dir = restore_dir / "reports"

        restore_meta = backup_service.restore_backup(
            backup_dir=backup_dir,
            target_db_path=restore_db,
            target_workbooks_dir=restore_wb_dir,
            target_reports_dir=restore_rep_dir,
            verify_hashes=True,
        )

        self.assertEqual(restore_meta["restored_workbooks"], 1)
        self.assertEqual(restore_meta["restored_reports"], 1)

        # 3. Assert PDF file recreated with IDENTICAL SHA-256 hash
        restored_pdf = restore_rep_dir / "2026" / "SRS_Kumaran_Generation_2026-05_rev1.pdf"
        self.assertTrue(restored_pdf.exists())
        restored_pdf_hash = hashlib.sha256(restored_pdf.read_bytes()).hexdigest()
        self.assertEqual(
            restored_pdf_hash,
            self.orig_pdf_hash,
            "Restored PDF hash must exactly match original PDF hash before backup!",
        )

        # 4. Assert Excel workbook recreated with IDENTICAL SHA-256 hash
        restored_excel = restore_wb_dir / "2026" / "SRS_Kumaran_Generation_2026.xlsx"
        self.assertTrue(restored_excel.exists())
        restored_excel_hash = hashlib.sha256(restored_excel.read_bytes()).hexdigest()
        self.assertEqual(
            restored_excel_hash,
            self.orig_excel_hash,
            "Restored Excel hash must exactly match original Excel hash before backup!",
        )

        # 5. Assert Database restored and records are queryable
        conn = sqlite3.connect(str(restore_db))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM readings WHERE status = 'ACTIVE'")
        row_count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(row_count, 5, "Restored database must contain all active readings")


if __name__ == "__main__":
    unittest.main()
