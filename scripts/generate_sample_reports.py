"""Script to generate sample May 1-18 PDF and Excel workbook from seed data."""

from datetime import date
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.domain.models import DailyReadingInput, MonthStatus
from app.infra.clock import FakeClock
from app.infra.db import init_db
from app.infra.models import Base
from app.infra.settings import settings
from app.services.csv_importer import import_csv_file
from app.services.reading_service import ReadingService
from app.services.reports.excel import ExcelReportGenerator
from app.services.reports.pdf import PDFReportGenerator


def generate_reports() -> None:
    clock = FakeClock()
    csv_path = BASE_DIR / "seed" / "may_2026.csv"

    # Use in-memory or file database
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    init_db(engine_override=engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        print(f"Importing seed data from {csv_path}...")
        count, _ = import_csv_file(
            file_path=csv_path,
            session=session,
            clock=clock,
        )
        session.commit()
        print(f"Imported {count} daily records.")

        service = ReadingService(clock)
        readings = service.get_readings_for_month(session, 2026, 5)

        reading_inputs = [
            DailyReadingInput(
                report_date=r.report_date,
                inverter_kwh=r.inverter_kwh,
                eb_export_kwh=r.eb_export_kwh,
                eb_6to10_kwh=r.eb_6to10_kwh,
                reported_monthly_kwh=r.reported_monthly_kwh,
                reported_yearly_kwh=r.reported_yearly_kwh,
                inverter_availability_pct=r.inverter_availability_pct,
                grid_availability_pct=r.grid_availability_pct,
                fault_text=r.fault_text,
                plant_weather_text=r.plant_weather_text,
                plant_temp_c=r.plant_temp_c,
                manual_remark=r.manual_remark,
                auto_remark=r.auto_remark,
                entry_method=r.entry_method,
                actor_label=r.actor_label,
            )
            for r in readings
        ]

        # 1. Generate PDF Report for May 1 to 18
        pdf_gen = PDFReportGenerator(output_dir=settings.REPORTS_DIR)
        pdf_file = pdf_gen.generate_monthly_pdf(
            year=2026,
            month=5,
            readings=reading_inputs,
            clock=clock,
            revision=1,
            start_day=1,
            end_day=18,
            custom_footer_date_str="01-Jun-2026 00:05 IST",
        )
        print(f"[OK] Generated PDF report: {pdf_file}")

        # 2. Generate Annual Excel Workbook
        excel_gen = ExcelReportGenerator(output_dir=settings.WORKBOOKS_DIR)
        excel_file = excel_gen.generate_annual_workbook(
            year=2026,
            readings_by_month={5: reading_inputs},
            month_statuses={5: MonthStatus.CLOSED},
            month_revisions={5: 1},
        )
        print(f"[OK] Generated Excel workbook: {excel_file}")


if __name__ == "__main__":
    generate_reports()
