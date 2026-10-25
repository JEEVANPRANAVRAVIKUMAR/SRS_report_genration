"""Excel workbook generator matching docs/SPEC.md Section B8."""

import calendar
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional
import xlsxwriter
from app.domain.models import DailyReadingInput, DailyTotals, MonthStatus
from app.domain.months import format_month_label, get_month_calendar_dates, get_month_days_count
from app.domain.totals import calculate_running_totals, summarize_month
from app.infra.settings import settings
from app.services.reports.atomic import atomic_write


class ExcelReportGenerator:
    """Generates the annual Excel workbook containing monthly sheets, year summary, and details."""

    def __init__(self, output_dir: Optional[Path] = None) -> None:
        self.output_dir = output_dir or settings.WORKBOOKS_DIR

    def generate_annual_workbook(
        self,
        year: int,
        readings_by_month: Dict[int, List[DailyReadingInput]],
        month_statuses: Optional[Dict[int, MonthStatus]] = None,
        month_revisions: Optional[Dict[int, int]] = None,
    ) -> Path:
        """Build the full calendar year Excel workbook atomically.
        
        Saved to workbooks/YYYY/SRS_Kumaran_Generation_YYYY.xlsx
        """
        dest_dir = self.output_dir / str(year)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / f"SRS_Kumaran_Generation_{year}.xlsx"

        def _write(temp_path: Path) -> None:
            workbook = xlsxwriter.Workbook(str(temp_path), {"constant_memory": False})
            self._create_workbook_content(
                workbook=workbook,
                year=year,
                readings_by_month=readings_by_month,
                month_statuses=month_statuses or {},
                month_revisions=month_revisions or {},
            )
            workbook.close()

        atomic_write(dest_file, _write)
        return dest_file

    def _create_workbook_content(
        self,
        workbook: xlsxwriter.Workbook,
        year: int,
        readings_by_month: Dict[int, List[DailyReadingInput]],
        month_statuses: Dict[int, MonthStatus],
        month_revisions: Dict[int, int],
    ) -> None:
        # Define formats (Calibri 11, blue grid #5B9BD5, banding #DDEBF7)
        grid_color = "#5B9BD5"
        alt_bg_color = "#DDEBF7"

        base_format_dict = {
            "font_name": "Calibri",
            "font_size": 11,
            "border": 1,
            "border_color": grid_color,
        }

        # Header format: bold, centered, vertically centered, wrapped
        header_format = workbook.add_format({
            **base_format_dict,
            "bold": True,
            "align": "center",
            "valign": "vcenter",
            "text_wrap": True,
        })

        month_box_format = workbook.add_format({
            **base_format_dict,
            "bold": True,
            "align": "center",
            "valign": "vcenter",
        })

        # Regular rows
        cell_date = workbook.add_format({
            **base_format_dict,
            "align": "center",
            "valign": "vcenter",
            "num_format": "m/d/yyyy",
        })
        cell_date_alt = workbook.add_format({
            **base_format_dict,
            "align": "center",
            "valign": "vcenter",
            "num_format": "m/d/yyyy",
            "bg_color": alt_bg_color,
        })

        cell_inv = workbook.add_format({
            **base_format_dict,
            "align": "right",
            "valign": "vcenter",
            "num_format": "0.00",
        })
        cell_inv_alt = workbook.add_format({
            **base_format_dict,
            "align": "right",
            "valign": "vcenter",
            "num_format": "0.00",
            "bg_color": alt_bg_color,
        })

        cell_eb = workbook.add_format({
            **base_format_dict,
            "align": "right",
            "valign": "vcenter",
            "num_format": "0",  # integer per sample
        })
        cell_eb_alt = workbook.add_format({
            **base_format_dict,
            "align": "right",
            "valign": "vcenter",
            "num_format": "0",
            "bg_color": alt_bg_color,
        })

        cell_eb_total = workbook.add_format({
            **base_format_dict,
            "align": "right",
            "valign": "vcenter",
            "num_format": "0.00",
        })
        cell_eb_total_alt = workbook.add_format({
            **base_format_dict,
            "align": "right",
            "valign": "vcenter",
            "num_format": "0.00",
            "bg_color": alt_bg_color,
        })

        cell_remark = workbook.add_format({
            **base_format_dict,
            "align": "left",
            "valign": "vcenter",
            "text_wrap": True,
        })
        cell_remark_alt = workbook.add_format({
            **base_format_dict,
            "align": "left",
            "valign": "vcenter",
            "text_wrap": True,
            "bg_color": alt_bg_color,
        })

        cell_empty = workbook.add_format({**base_format_dict})
        cell_empty_alt = workbook.add_format({**base_format_dict, "bg_color": alt_bg_color})

        # Generate month sheets
        active_months = sorted(readings_by_month.keys())
        for m in active_months:
            sheet_name = format_month_label(year, m)
            ws = workbook.add_worksheet(sheet_name)
            self._write_month_sheet(
                ws=ws,
                year=year,
                month=m,
                readings=readings_by_month.get(m, []),
                formats={
                    "header": header_format,
                    "month_box": month_box_format,
                    "date": cell_date,
                    "date_alt": cell_date_alt,
                    "inv": cell_inv,
                    "inv_alt": cell_inv_alt,
                    "eb": cell_eb,
                    "eb_alt": cell_eb_alt,
                    "eb_total": cell_eb_total,
                    "eb_total_alt": cell_eb_total_alt,
                    "remark": cell_remark,
                    "remark_alt": cell_remark_alt,
                    "empty": cell_empty,
                    "empty_alt": cell_empty_alt,
                },
            )

        # Generate Year Summary sheet
        self._write_year_summary(
            ws=workbook.add_worksheet("Year Summary"),
            year=year,
            readings_by_month=readings_by_month,
            month_statuses=month_statuses,
            month_revisions=month_revisions,
            header_format=header_format,
            cell_inv=cell_inv,
            cell_eb_total=cell_eb_total,
        )

        # Generate Details sheet
        self._write_details_sheet(
            ws=workbook.add_worksheet("Details"),
            year=year,
            readings_by_month=readings_by_month,
            header_format=header_format,
            base_format_dict=base_format_dict,
            workbook=workbook,
        )

    def _write_month_sheet(
        self,
        ws: xlsxwriter.worksheet.Worksheet,
        year: int,
        month: int,
        readings: List[DailyReadingInput],
        formats: Dict[str, xlsxwriter.format.Format],
    ) -> None:
        # Page & Print Setup
        ws.set_paper(9)  # A4
        ws.set_portrait()
        ws.fit_to_pages(1, 0)  # Fit to 1 page wide
        ws.repeat_rows(0, 1)   # Repeat row 1 & 2 on print

        # Column widths matching sample
        ws.set_column(0, 0, 12)  # Date
        ws.set_column(1, 1, 11)  # Inverter
        ws.set_column(2, 2, 13)  # Monthly Inverter Total
        ws.set_column(3, 3, 11)  # EB Reading
        ws.set_column(4, 4, 13)  # EB Reading Total
        ws.set_column(5, 5, 11)  # 6am-10am
        ws.set_column(6, 6, 26)  # Remarks

        # Freeze headers after row 2
        ws.freeze_panes(2, 0)

        # Header Rows: Rows 0 and 1 (1-indexed: Row 1 & 2)
        h = formats["header"]
        ws.merge_range(0, 0, 1, 0, "Date", h)
        ws.merge_range(0, 1, 1, 1, "Inverter", h)
        ws.merge_range(0, 2, 1, 2, "Monthly\nInverter\nTotal", h)
        ws.merge_range(0, 3, 1, 3, "EB Reading", h)
        ws.merge_range(0, 4, 1, 4, "EB Reading\nTotal", h)
        ws.merge_range(0, 5, 1, 5, "6am-\n10am", h)

        # Month Box in G1 (0, 6) and Remarks in G2 (1, 6)
        ws.write_string(0, 6, format_month_label(year, month), formats["month_box"])
        ws.write_string(1, 6, "Remarks", h)

        # Precompute dynamic running totals
        running_totals = calculate_running_totals(readings, remark_mode=settings.REMARK_MODE)
        totals_by_date = {t.report_date: t for t in running_totals}

        # Render one row for EVERY calendar day (28 to 31 rows)
        all_dates = get_month_calendar_dates(year, month)
        row_idx = 2  # Starts at row 3 (0-indexed: 2)

        for d in all_dates:
            is_alt = (d.day % 2 == 1)  # Alternate rows light blue (1st, 3rd, 5th...)
            f_date = formats["date_alt"] if is_alt else formats["date"]
            f_inv = formats["inv_alt"] if is_alt else formats["inv"]
            f_eb = formats["eb_alt"] if is_alt else formats["eb"]
            f_eb_total = formats["eb_total_alt"] if is_alt else formats["eb_total"]
            f_remark = formats["remark_alt"] if is_alt else formats["remark"]
            f_empty = formats["empty_alt"] if is_alt else formats["empty"]

            # Write date string formatted as m/d/yyyy
            date_str = f"{d.month}/{d.day}/{d.year}"
            ws.write_string(row_idx, 0, date_str, f_date)

            if d in totals_by_date:
                t = totals_by_date[d]
                ws.write_number(row_idx, 1, t.inverter_kwh, f_inv)
                ws.write_number(row_idx, 2, t.running_inverter_total, f_inv)
                ws.write_number(row_idx, 3, t.eb_export_kwh, f_eb)
                ws.write_number(row_idx, 4, t.running_eb_total, f_eb_total)
                ws.write_number(row_idx, 5, t.eb_6to10_kwh, f_inv)

                # Write remark safely as plain string (prevents formula injection)
                clean_remark = t.combined_remark.strip()
                ws.write_string(row_idx, 6, clean_remark, f_remark)
            else:
                # Gaps: empty cells, never zeros
                ws.write_blank(row_idx, 1, None, f_empty)
                ws.write_blank(row_idx, 2, None, f_empty)
                ws.write_blank(row_idx, 3, None, f_empty)
                ws.write_blank(row_idx, 4, None, f_empty)
                ws.write_blank(row_idx, 5, None, f_empty)
                ws.write_blank(row_idx, 6, None, f_empty)

            row_idx += 1

    def _write_year_summary(
        self,
        ws: xlsxwriter.worksheet.Worksheet,
        year: int,
        readings_by_month: Dict[int, List[DailyReadingInput]],
        month_statuses: Dict[int, MonthStatus],
        month_revisions: Dict[int, int],
        header_format: xlsxwriter.format.Format,
        cell_inv: xlsxwriter.format.Format,
        cell_eb_total: xlsxwriter.format.Format,
    ) -> None:
        ws.set_column(0, 0, 15)  # Month
        ws.set_column(1, 1, 14)  # Days Recorded
        ws.set_column(2, 2, 16)  # Inverter Total
        ws.set_column(3, 3, 16)  # EB Total
        ws.set_column(4, 4, 16)  # Daily Average
        ws.set_column(5, 5, 12)  # Status
        ws.set_column(6, 6, 12)  # PDF Rev

        headers = [
            "Month", "Days Recorded", "Inverter Total (kWh)",
            "EB Total (kWh)", "Daily Average (kWh)", "Status", "PDF Rev",
        ]
        for col_idx, text in enumerate(headers):
            ws.write_string(0, col_idx, text, header_format)

        for m in range(1, 13):
            readings = readings_by_month.get(m, [])
            status = month_statuses.get(m, MonthStatus.OPEN)
            rev = month_revisions.get(m, 1)

            summary = summarize_month(
                year=year,
                month=m,
                readings=readings,
                status=status,
                pdf_revision=rev,
            )

            row_idx = m
            ws.write_string(row_idx, 0, format_month_label(year, m))
            ws.write_number(row_idx, 1, summary.days_recorded)
            ws.write_number(row_idx, 2, summary.total_inverter_kwh, cell_inv)
            ws.write_number(row_idx, 3, summary.total_eb_kwh, cell_eb_total)
            ws.write_number(row_idx, 4, summary.average_daily_inverter_kwh, cell_inv)
            ws.write_string(row_idx, 5, summary.status.value)
            ws.write_number(row_idx, 6, summary.pdf_revision)

    def _write_details_sheet(
        self,
        ws: xlsxwriter.worksheet.Worksheet,
        year: int,
        readings_by_month: Dict[int, List[DailyReadingInput]],
        header_format: xlsxwriter.format.Format,
        base_format_dict: dict,
        workbook: xlsxwriter.Workbook,
    ) -> None:
        headers = [
            "Date", "Inverter kWh", "EB Export kWh", "6am-10am kWh",
            "Plant Monthly kWh", "Plant Yearly kWh", "Inv Avail %",
            "Grid Avail %", "Fault Text", "Plant Weather", "Plant Temp °C",
            "Remarks", "Entry Method", "Actor",
        ]
        for c, h in enumerate(headers):
            ws.write_string(0, c, h, header_format)

        all_readings: List[DailyReadingInput] = []
        for m in sorted(readings_by_month.keys()):
            all_readings.extend(readings_by_month[m])
        all_readings.sort(key=lambda r: r.report_date)

        for r_idx, r in enumerate(all_readings, start=1):
            ws.write_string(r_idx, 0, str(r.report_date))
            ws.write_number(r_idx, 1, r.inverter_kwh or 0.0)
            ws.write_number(r_idx, 2, r.eb_export_kwh or 0.0)
            ws.write_number(r_idx, 3, r.eb_6to10_kwh or 0.0)
            if r.reported_monthly_kwh is not None:
                ws.write_number(r_idx, 4, r.reported_monthly_kwh)
            if r.reported_yearly_kwh is not None:
                ws.write_number(r_idx, 5, r.reported_yearly_kwh)
            ws.write_number(r_idx, 6, r.inverter_availability_pct or 100.0)
            ws.write_number(r_idx, 7, r.grid_availability_pct or 100.0)
            # Safe string writing
            ws.write_string(r_idx, 8, r.fault_text or "")
            ws.write_string(r_idx, 9, r.plant_weather_text or "")
            if r.plant_temp_c is not None:
                ws.write_number(r_idx, 10, r.plant_temp_c)
            ws.write_string(r_idx, 11, r.manual_remark or "")
            ws.write_string(r_idx, 12, r.entry_method.value)
            ws.write_string(r_idx, 13, r.actor_label)
