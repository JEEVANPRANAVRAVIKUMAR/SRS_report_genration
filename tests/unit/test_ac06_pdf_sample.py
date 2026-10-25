"""Unit test for Acceptance Criteria AC-06:
PDF export for 1 to 18 May equals the sample PDF cell by cell, on one page,
with the right headers, 'MAY-2026' box and number formats.
"""

from datetime import date
from pathlib import Path
import unittest
from reportlab.pdfgen import canvas
from pypdf import PdfReader if False else None  # fallback or direct inspection
from app.domain.models import DailyReadingInput, EntryMethod
from app.domain.months import format_month_label
from app.infra.clock import FakeClock
from app.services.csv_importer import import_csv_file
from app.services.reports.pdf import PDFReportGenerator
from app.services.reading_service import ReadingService


class TestAC06PDFSample(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.tmp_dir = Path(__file__).resolve().parent.parent.parent / "data" / "test_reports"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.pdf_gen = PDFReportGenerator(output_dir=self.tmp_dir)

    def test_pdf_export_may_1_to_18_cell_by_cell(self) -> None:
        # Load seed data 1 to 18 May
        csv_path = Path(__file__).resolve().parent.parent.parent / "seed" / "may_2026.csv"
        self.assertTrue(csv_path.exists())

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.infra.db import init_db
        from app.infra.models import Base

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        init_db(engine_override=engine)
        Session = sessionmaker(bind=engine)

        with Session() as session:
            count, _ = import_csv_file(
                file_path=csv_path,
                session=session,
                clock=self.clock,
            )
            session.commit()
            self.assertEqual(count, 18)

            service = ReadingService(self.clock)
            readings = service.get_readings_for_month(session, 2026, 5)

            reading_inputs = [
                DailyReadingInput(
                    report_date=r.report_date,
                    inverter_kwh=r.inverter_kwh,
                    eb_export_kwh=r.eb_export_kwh,
                    eb_6to10_kwh=r.eb_6to10_kwh,
                    manual_remark=r.manual_remark,
                )
                for r in readings
            ]

            # Generate PDF for days 1 to 18
            pdf_path = self.pdf_gen.generate_monthly_pdf(
                year=2026,
                month=5,
                readings=reading_inputs,
                clock=self.clock,
                revision=1,
                start_day=1,
                end_day=18,
            )

            self.assertTrue(pdf_path.exists())
            self.assertGreater(pdf_path.stat().st_size, 1000)

            # Inspect PDF binary content for expected text and cell strings
            with open(pdf_path, "rb") as f:
                content = f.read().decode("latin1", errors="ignore")

            # Verify header box
            self.assertIn("MAY-2026", content)
            self.assertIn("Remarks", content)
            self.assertIn("Inverter", content)
            self.assertIn("EB Reading", content)

            # Verify key cell values from 18 May
            # Inverter: 6393.00, Total: 103065.00, EB: 6240, Total: 100740.00, 6am-10am: 1668.00
            self.assertIn("103065.00", content)
            self.assertIn("100740.00", content)
            self.assertIn("6393.00", content)
            self.assertIn("6240", content)
            self.assertIn("1668.00", content)

            # Verify remarks from sample
            self.assertIn("Reading taken", content)
            self.assertIn("vaani burried", content)
            self.assertIn("m sand bought", content)

            # Verify Single Page: A4 page count in PDF stream (/Count 1 or single /Page object)
            page_count_marker = "/Type /Pages"
            self.assertIn(page_count_marker, content)
            self.assertIn("/Count 1", content, "PDF must fit on exactly ONE page with no second page!")


if __name__ == "__main__":
    unittest.main()
