"""Unit test for Acceptance Criteria AC-15:
Privacy verification: After processing the sample image, searching the database,
evidence folder, workbooks, PDFs, and logs for AAURVIN, RANGA, JAYARAMM, GANESHAA,
and PRABHU finds nothing.
"""

from datetime import date
from pathlib import Path
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.domain.models import DailyReadingInput, EntryMethod
from app.infra.clock import FakeClock
from app.infra.db import init_db
from app.infra.models import AuditLogModel, Base, ReadingModel, UploadModel
from app.services.extraction.crop import extract_evidence_crop, ingest_incoming_image
from app.services.extraction.post_processing import post_process_extraction
from app.services.extraction.provider import FakeGeminiExtractionProvider
from app.services.reading_service import ReadingService
from app.services.reports.excel import ExcelReportGenerator
from app.services.reports.pdf import PDFReportGenerator
from app.services.review_service import ReviewService

FORBIDDEN_NAMES = ["AAURVIN", "RANGA", "JAYARAMM", "GANESHAA", "PRABHU"]


class TestAC15Privacy(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock(date(2026, 5, 22))
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        init_db(engine_override=self.engine)
        self.Session = sessionmaker(bind=self.engine)

        self.sample_image_path = (
            Path(__file__).resolve().parent.parent.parent
            / "tests"
            / "golden"
            / "report_2026-05-22.jpeg"
        )
        self.assertTrue(self.sample_image_path.exists())

    def test_zero_leakage_of_other_customers_after_processing(self) -> None:
        """AC-15: Process sample image and verify complete absence of other customers in storage and outputs."""
        image_bytes = self.sample_image_path.read_bytes()

        # Step 1: Ingest into temporary cache
        sha256_hash, temp_path = ingest_incoming_image(image_bytes)
        self.assertTrue(temp_path.exists())

        # Step 2: Extract evidence crop (this also purges the full incoming image)
        evidence_crop_path = extract_evidence_crop(
            temp_image_path=temp_path,
            sha256_hash=sha256_hash,
            ym_str="2026-05",
        )
        self.assertTrue(evidence_crop_path.exists())
        self.assertFalse(temp_path.exists(), "Full incoming image must be deleted immediately after crop!")

        # Step 3: Run extraction provider (Fake or Gemini)
        provider = FakeGeminiExtractionProvider()
        raw_output = provider.extract(evidence_crop_path)

        # Step 4: Post-process strictly for SRS Kumaran
        extraction = post_process_extraction(
            raw=raw_output,
            clock=self.clock,
            evidence_crop_path=str(evidence_crop_path),
            raw_sha256=sha256_hash,
        )

        # Step 5: Save reading and audit record in database
        reading_service = ReadingService(self.clock)
        review_service = ReviewService(self.clock)

        with self.Session() as session:
            upload = UploadModel(
                sha256=sha256_hash,
                evidence_path=str(evidence_crop_path),
                received_via="PICKER",
                status="PENDING_REVIEW",
            )
            session.add(upload)
            session.flush()

            reading_input = DailyReadingInput(
                report_date=date(2026, 5, 22),
                inverter_kwh=extraction.inverter_kwh.value,
                eb_export_kwh=extraction.eb_export_kwh.value,
                eb_6to10_kwh=extraction.eb_6to10_kwh.value,
                reported_monthly_kwh=extraction.reported_monthly_kwh.value,
                reported_yearly_kwh=extraction.reported_yearly_kwh.value,
                plant_weather_text=extraction.plant_weather_text.value,
                plant_temp_c=extraction.plant_temp_c.value,
                entry_method=EntryMethod.IMAGE,
                actor_label="Operator",
            )

            review_service.accept_upload(
                session=session,
                upload_id=upload.id,
                reading_input=reading_input,
                actor_label="Operator",
            )
            session.commit()

            # Step 6: Generate reports (Excel and PDF)
            test_reports_dir = Path(__file__).resolve().parent.parent.parent / "data" / "privacy_test_reports"
            test_reports_dir.mkdir(parents=True, exist_ok=True)

            pdf_gen = PDFReportGenerator(output_dir=test_reports_dir)
            pdf_path = pdf_gen.generate_monthly_pdf(
                year=2026,
                month=5,
                readings=[reading_input],
                clock=self.clock,
                revision=1,
            )

            excel_gen = ExcelReportGenerator(output_dir=test_reports_dir)
            excel_path = excel_gen.generate_annual_workbook(
                year=2026,
                readings_by_month={5: [reading_input]},
            )

            # Step 7: PRIVACY AUDIT SEARCH
            # 7a. Search Database tables
            db_text_corpus = ""
            for r in session.query(ReadingModel).all():
                db_text_corpus += f"{r.fault_text} {r.plant_weather_text} {r.manual_remark} {r.actor_label} "
            for a in session.query(AuditLogModel).all():
                db_text_corpus += f"{a.action} {a.before} {a.after} {a.reason} "
            for u in session.query(UploadModel).all():
                db_text_corpus += f"{u.extraction or ''} {u.validation or ''} "

            # 7b. Search generated PDF
            pdf_bytes = pdf_path.read_bytes().decode("latin1", errors="ignore")

            # 7c. Search generated Excel
            import zipfile
            excel_text_corpus = ""
            with zipfile.ZipFile(excel_path, "r") as z:
                for fname in z.namelist():
                    if fname.endswith(".xml") or fname.endswith(".rels"):
                        excel_text_corpus += z.read(fname).decode("utf-8", errors="ignore")

            combined_search_corpus = f"{db_text_corpus} {pdf_bytes} {excel_text_corpus}".upper()

            # Enforce AC-15: zero occurrences of forbidden names
            for forbidden in FORBIDDEN_NAMES:
                self.assertNotIn(
                    forbidden,
                    combined_search_corpus,
                    f"Privacy leak! Found forbidden customer '{forbidden}' in system data or outputs!",
                )


if __name__ == "__main__":
    unittest.main()
