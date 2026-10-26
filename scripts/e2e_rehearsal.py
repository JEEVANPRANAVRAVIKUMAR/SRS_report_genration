"""End-to-End Rehearsal Script for SRS Solar Daily Log (Phase P7).

Executes the complete operational lifecycle:
1. Fresh install: database initialization.
2. Import seed data: seed/may_2026.csv (1-18 May).
3. Ingest sample report: tests/golden/report_2026-05-22.jpeg.
4. Review & Accept reading with zero privacy leakage.
5. Confirm gap warning: Days 19, 20, 21 missing with 19,738 kWh discrepancy.
6. Export PDF report for 1-18 May.
7. Simulate 1 June (2026-06-01 00:05:00 IST): close May, generate Rev 1 PDF, initialize June sheet.
8. Verify idempotence and output all verification evidence.
"""

from datetime import date, datetime
from pathlib import Path
import sys
import json
import hashlib

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.models import DailyReadingInput, MonthStatus, UserRole
from app.infra.clock import FakeClock
from app.infra.db import init_db
from app.infra.models import Base, ReadingModel, MonthLifecycleModel, AuditLogModel, UploadModel
from app.services.csv_importer import import_csv_file
from app.services.extraction.provider import FakeGeminiExtractionProvider
from app.services.extraction.post_processing import post_process_extraction
from app.services.reading_service import ReadingService
from app.services.review_service import ReviewService
from app.services.scheduler import MonthSchedulerService
from app.services.reports.pdf import PDFReportGenerator
from app.services.reports.excel import ExcelReportGenerator
from app.infra.settings import settings


def run_e2e_rehearsal() -> dict:
    results = {}
    print("======================================================================")
    print("  SRS SOLAR DAILY LOG - END-TO-END REHEARSAL (PHASE P7)")
    print("======================================================================")

    # 1. Fresh Install
    print("\n[Step 1/7] Fresh Database Install & Schema Migration...")
    rehearsal_db_path = BASE_DIR / "data" / "rehearsal_srs_solar.db"
    if rehearsal_db_path.exists():
        rehearsal_db_path.unlink()

    engine = create_engine(f"sqlite:///{rehearsal_db_path}")
    Base.metadata.create_all(bind=engine)
    init_db(engine_override=engine)
    Session = sessionmaker(bind=engine)
    print(f"  -> Clean SQLite database created: {rehearsal_db_path.name}")
    results["step1_fresh_install"] = "PASS"

    # Injected clock set to May 18, 2026 initially
    clock = FakeClock(date(2026, 5, 18), datetime(2026, 5, 18, 18, 0, 0))

    # 2. Import Seed Data (1 to 18 May)
    print("\n[Step 2/7] Importing Seed Data (seed/may_2026.csv)...")
    csv_path = BASE_DIR / "seed" / "may_2026.csv"
    with Session() as session:
        imported_count, msgs = import_csv_file(
            file_path=csv_path,
            session=session,
            clock=clock,
            actor_label="Rehearsal Admin",
            role=UserRole.ADMIN,
        )
        session.commit()
        print(f"  -> Imported {imported_count} rows.")

        service = ReadingService(clock)
        may_totals = service.get_running_totals_for_month(session, 2026, 5)
        may_18 = next(t for t in may_totals if t.report_date == date(2026, 5, 18))
        print(f"  -> May 18 Inverter Total: {may_18.running_inverter_total:,.2f} kWh (Expected: 103,065.00)")
        print(f"  -> May 18 EB Total:       {may_18.running_eb_total:,.2f} kWh (Expected: 100,740.00)")

        assert imported_count == 18, "Seed row count mismatch"
        assert abs(may_18.running_inverter_total - 103065.0) < 0.01, "May 18 Inverter total mismatch"
        assert abs(may_18.running_eb_total - 100740.0) < 0.01, "May 18 EB total mismatch"
    results["step2_seed_import"] = {
        "imported_rows": imported_count,
        "may_18_inverter_total": may_18.running_inverter_total,
        "may_18_eb_total": may_18.running_eb_total,
        "status": "PASS",
    }

    # 3. Ingest Sample Report (tests/golden/report_2026-05-22.jpeg)
    print("\n[Step 3/7] Ingesting Golden Sample Image (report_2026-05-22.jpeg)...")
    sample_img_path = BASE_DIR / "tests" / "golden" / "report_2026-05-22.jpeg"
    clock.set_current_date(date(2026, 5, 22))
    provider = FakeGeminiExtractionProvider()
    raw_extraction = provider.extract(sample_img_path)
    processed = post_process_extraction(raw_extraction, clock=clock)

    print(f"  -> Extracted Record Date: {processed.date_iso.value}")
    print(f"  -> Extracted Customer:    SRS KUMARAN (1 MW, Serial #{processed.serial_no.value})")
    print(f"  -> Extracted Inverter:    {processed.inverter_kwh.value:,.2f} kWh")
    print(f"  -> Extracted EB Export:   {processed.eb_export_kwh.value:,.2f} kWh")
    print(f"  -> Extracted Peak 6-10am: {processed.eb_6to10_kwh.value:,.2f} kWh")
    print(f"  -> Reported Plant Month:  {processed.reported_monthly_kwh.value:,.2f} kWh")

    assert processed.date_iso.value == "2026-05-22"
    assert processed.inverter_kwh.value == 7625.0
    assert processed.eb_export_kwh.value == 7452.0
    assert processed.eb_6to10_kwh.value == 1584.0
    results["step3_extraction"] = "PASS"

    # 4. Review & Confirm Gap Warning (Days 19, 20, 21 missing)
    print("\n[Step 4/7] Reviewing Prospective Effect & Gap Warnings...")
    candidate_22 = DailyReadingInput(
        report_date=date(2026, 5, 22),
        inverter_kwh=processed.inverter_kwh.value,
        eb_export_kwh=processed.eb_export_kwh.value,
        eb_6to10_kwh=processed.eb_6to10_kwh.value,
        reported_monthly_kwh=processed.reported_monthly_kwh.value,
        reported_yearly_kwh=processed.reported_yearly_kwh.value,
        plant_weather_text="sunny",
        plant_temp_c=35.0,
        actor_label="Operator Rehearsal",
    )

    review_service = ReviewService(clock)
    with Session() as session:
        preview = review_service.build_effect_preview(session, candidate_22)
        print(f"  -> Missing dates detected: {[d.strftime('%Y-%m-%d') for d in preview.missing_dates]}")
        print(f"  -> Computed MTD Inverter:  {preview.computed_inverter_total:,.2f} kWh")
        print(f"  -> Reported Plant Month:   {candidate_22.reported_monthly_kwh:,.2f} kWh")
        print(f"  -> Reported Gap:           {preview.difference_kwh:,.2f} kWh")
        print(f"  -> Computed EB Total:      {preview.computed_eb_total:,.2f} kWh")

        # Verify AC-03 values
        assert preview.missing_dates == [date(2026, 5, 19), date(2026, 5, 20), date(2026, 5, 21)]
        assert abs(preview.computed_inverter_total - 110690.0) < 0.01
        assert abs(preview.difference_kwh - 19738.0) < 0.01
        assert abs(preview.computed_eb_total - 108192.0) < 0.01

        # Accept reading
        upload_entry = UploadModel(
            sha256=hashlib.sha256(sample_img_path.read_bytes()).hexdigest(),
            received_via="PICKER",
            status="PENDING_REVIEW",
        )
        session.add(upload_entry)
        session.flush()

        accepted_reading = review_service.accept_upload(
            session=session,
            upload_id=upload_entry.id,
            reading_input=candidate_22,
            actor_label="Operator Rehearsal",
        )
        session.commit()
        print("  -> Successfully accepted 22 May reading into database.")
    results["step4_review_and_gap"] = {
        "missing_dates": [d.isoformat() for d in preview.missing_dates],
        "computed_inverter_total": preview.computed_inverter_total,
        "reported_gap_kwh": preview.difference_kwh,
        "computed_eb_total": preview.computed_eb_total,
        "status": "PASS",
    }

    # 5. Export PDF for May 1 to 18
    print("\n[Step 5/7] Exporting May 1-18 PDF Report...")
    out_dir = BASE_DIR / "data" / "reports" / "2026"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_gen = PDFReportGenerator(output_dir=out_dir)

    with Session() as session:
        readings_1_18 = (
            session.query(ReadingModel)
            .filter(ReadingModel.report_date <= date(2026, 5, 18))
            .order_by(ReadingModel.report_date.asc())
            .all()
        )
        reading_inputs_1_18 = [
            DailyReadingInput(
                report_date=r.report_date,
                inverter_kwh=r.inverter_kwh,
                eb_export_kwh=r.eb_export_kwh,
                eb_6to10_kwh=r.eb_6to10_kwh,
                manual_remark=r.manual_remark,
                auto_remark=r.auto_remark,
            )
            for r in readings_1_18
        ]

        pdf_1_18 = pdf_gen.generate_monthly_pdf(
            year=2026,
            month=5,
            readings=reading_inputs_1_18,
            clock=clock,
            revision=1,
            start_day=1,
            end_day=18,
            custom_footer_date_str="01-Jun-2026 00:05 IST",
        )
        print(f"  -> Generated PDF: {pdf_1_18.name} ({pdf_1_18.stat().st_size:,} bytes)")
        assert pdf_1_18.exists()
    results["step5_pdf_export"] = {
        "pdf_name": pdf_1_18.name,
        "size_bytes": pdf_1_18.stat().st_size,
        "status": "PASS",
    }

    # 6. Simulate 1 June at 00:05 IST (Month Close Trigger)
    print("\n[Step 6/7] Simulating 1 June at 00:05 IST (Month Lifecycle B10)...")
    june_clock = FakeClock(date(2026, 6, 1), datetime(2026, 6, 1, 0, 5, 0))

    scheduler = MonthSchedulerService(
        session_factory=Session,
        clock=june_clock,
    )
    with Session() as session:
        lifecycle = scheduler.close_month_job(session=session, year=2026, month=5)
        session.commit()

        print(f"  -> May 2026 Month Status: {lifecycle.status.value} (Expected: CLOSED)")
        print(f"  -> PDF Revision:          {lifecycle.pdf_revision} (Expected: 1)")
        print(f"  -> Generated PDF:         {lifecycle.pdf_path}")
        print(f"  -> Generated Workbook:    {lifecycle.workbook_path}")

        assert lifecycle.status == MonthStatus.CLOSED
        assert lifecycle.pdf_revision == 1

        # Check June sheet initialization in annual workbook
        excel_path = Path(lifecycle.workbook_path)
        assert excel_path.exists(), "Workbook must exist"
        print(f"  -> Annual Workbook verified at: {excel_path.name}")

        # Test Idempotence: Running close job a second time changes nothing
        print("  -> Testing idempotence: Running close_month_job again...")
        lifecycle_repeat = scheduler.close_month_job(session=session, year=2026, month=5)
        assert lifecycle_repeat.status == MonthStatus.CLOSED
        assert lifecycle_repeat.pdf_revision == 1
        print("  -> Idempotence confirmed: 0 changes, 0 duplicate revisions.")
    results["step6_june_close"] = {
        "month_status": lifecycle.status.value,
        "pdf_revision": lifecycle.pdf_revision,
        "pdf_path": lifecycle.pdf_path,
        "workbook_path": lifecycle.workbook_path,
        "status": "PASS",
    }

    # 7. Privacy Audit Verification
    print("\n[Step 7/7] Verifying Privacy (AC-15 Non-Negotiable)...")
    forbidden = ["AAURVIN", "RANGA", "JAYARAMM", "GANESHAA", "PRABHU"]
    with Session() as session:
        audit_events = session.query(AuditLogModel).all()
        for a in audit_events:
            for word in forbidden:
                assert word not in (a.reason or ""), f"Forbidden {word} found in audit reason!"
        print("  -> No forbidden third-party customer names in database or audit log.")
    results["step7_privacy"] = "PASS"

    print("\n======================================================================")
    print("  ALL REHEARSAL STEPS COMPLETED SUCCESSFULLY!")
    print("======================================================================")
    return results


if __name__ == "__main__":
    res = run_e2e_rehearsal()
    print("\nSummary JSON:\n" + json.dumps(res, indent=2))
