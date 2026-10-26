"""PDF report generator reproducing sample PDF matching docs/SPEC.md Section B9."""

import calendar
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from app.domain.models import DailyReadingInput, DailyTotals
from app.domain.months import format_month_label, get_month_calendar_dates
from app.domain.totals import calculate_running_totals
from app.infra.clock import Clock
from app.infra.settings import settings
from app.services.reports.atomic import atomic_write


class NumberedCanvas(canvas.Canvas):
    """Canvas that draws the compliant footer on every page."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: List[dict] = []
        self.footer_text = ""

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_footer()
            super().showPage()
        super().save()

    def draw_footer(self) -> None:
        if self.footer_text:
            self.saveState()
            self.setFont("Helvetica", 7.5)
            self.setFillColor(colors.HexColor("#666666"))
            # Bottom margin at 25 points
            self.drawString(44, 25, self.footer_text)
            self.restoreState()


class PDFReportGenerator:
    """Generates monthly PDF reports matching tests/golden/may_2026_sample.pdf."""

    def __init__(self, output_dir: Optional[Path] = None) -> None:
        self.output_dir = output_dir or settings.REPORTS_DIR

    def generate_monthly_pdf(
        self,
        year: int,
        month: int,
        readings: List[DailyReadingInput],
        clock: Clock,
        revision: int = 1,
        start_day: Optional[int] = None,
        end_day: Optional[int] = None,
        reason: str = "CLOSE",
        custom_footer_date_str: Optional[str] = None,
    ) -> Path:
        """Generate monthly PDF report atomically.
        
        Saved to reports/YYYY/SRS_Kumaran_Generation_YYYY-MM_revX.pdf
        """
        dest_dir = self.output_dir / str(year)
        dest_dir.mkdir(parents=True, exist_ok=True)
        ym = f"{year:04d}-{month:02d}"
        dest_file = dest_dir / f"SRS_Kumaran_Generation_{ym}_rev{revision}.pdf"

        # Calculate running totals for the month (always from day 1)
        running_totals = calculate_running_totals(readings, remark_mode=settings.REMARK_MODE)
        totals_by_date = {t.report_date: t for t in running_totals}

        # Determine date range to render
        _, max_days = calendar.monthrange(year, month)
        first_d = start_day if start_day is not None else 1
        last_d = end_day if end_day is not None else max_days

        target_dates = [
            date(year, month, d)
            for d in range(first_d, last_d + 1)
        ]

        def _write(temp_path: Path) -> None:
            doc = SimpleDocTemplate(
                str(temp_path),
                pagesize=A4,
                leftMargin=44,
                rightMargin=44,
                topMargin=40,
                bottomMargin=40,
            )

            # Build Table Data
            # Header Row 1 & 2
            # G1 is Month Box, G2 is Remarks
            month_box_label = format_month_label(year, month)
            table_data = [
                # Row 0
                ["Date", "Inverter", "Monthly\nInverter\nTotal", "EB Reading", "EB Reading\nTotal", "6am-\n10am", month_box_label],
                # Row 1
                ["", "", "", "", "", "", "Remarks"],
            ]

            # Colors
            grid_blue = colors.HexColor("#5B9BD5")
            alt_blue = colors.HexColor("#DDEBF7")

            table_styles = [
                # Merges for headers
                ("SPAN", (0, 0), (0, 1)),  # Date
                ("SPAN", (1, 0), (1, 1)),  # Inverter
                ("SPAN", (2, 0), (2, 1)),  # Monthly Inverter Total
                ("SPAN", (3, 0), (3, 1)),  # EB Reading
                ("SPAN", (4, 0), (4, 1)),  # EB Reading Total
                ("SPAN", (5, 0), (5, 1)),  # 6am-10am
                # Header alignments & font
                ("FONTNAME", (0, 0), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 1), 8.5),
                ("ALIGN", (0, 0), (5, 1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (6, 0), (6, 0), "CENTER"),
                ("ALIGN", (6, 1), (6, 1), "LEFT"),
                # Gridlines
                ("INNERGRID", (0, 0), (-1, -1), 0.6, grid_blue),
                ("BOX", (0, 0), (-1, -1), 0.8, grid_blue),
                # Padding
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]

            styles = getSampleStyleSheet()
            remark_style = ParagraphStyle(
                "PDFRemark",
                parent=styles["Normal"],
                fontName="Helvetica",
                fontSize=7.5,
                leading=9,
            )

            missing_days_count = 0

            # Data rows
            for idx, d in enumerate(target_dates):
                row_idx = idx + 2
                date_str = f"{d.month}/{d.day}/{d.year}"

                is_alt = (d.day % 2 == 1)
                if is_alt:
                    table_styles.append(("BACKGROUND", (0, row_idx), (-1, row_idx), alt_blue))

                if d in totals_by_date:
                    t = totals_by_date[d]
                    inv_str = f"{t.inverter_kwh:.2f}"
                    inv_total_str = f"{t.running_inverter_total:.2f}"
                    eb_str = f"{int(round(t.eb_export_kwh))}"  # integer format per sample
                    eb_total_str = f"{t.running_eb_total:.2f}"
                    eb_6to10_str = f"{t.eb_6to10_kwh:.2f}"

                    remark_text = t.combined_remark.strip()
                    remark_para = Paragraph(remark_text, remark_style) if remark_text else ""

                    row = [date_str, inv_str, inv_total_str, eb_str, eb_total_str, eb_6to10_str, remark_para]
                else:
                    missing_days_count += 1
                    # Gaps: empty cells, with 'Not recorded' if full month-close
                    not_rec_para = Paragraph("Not recorded", remark_style)
                    row = [date_str, "", "", "", "", "", not_rec_para]

                table_data.append(row)

                # Column alignments for data row
                table_styles.append(("ALIGN", (0, row_idx), (0, row_idx), "CENTER"))
                table_styles.append(("ALIGN", (1, row_idx), (5, row_idx), "RIGHT"))
                table_styles.append(("ALIGN", (6, row_idx), (6, row_idx), "LEFT"))
                table_styles.append(("FONTNAME", (0, row_idx), (-1, row_idx), "Helvetica"))
                table_styles.append(("FONTSIZE", (0, row_idx), (-1, row_idx), 7.5))

            # Column Widths (Sum = 507 pt, margins = 44 + 44 = 88 pt -> Total = 595 pt A4)
            col_widths = [60, 62, 75, 60, 75, 55, 120]

            # Row Heights: Header ~20 pt each, Data rows ~16.5 pt each
            # 31 data rows * 16.5 + 40 header = 551 pt -> Fits strictly on 1 page!
            row_heights = [20, 16] + [16.5] * len(target_dates)

            pdf_table = Table(table_data, colWidths=col_widths, rowHeights=row_heights)
            pdf_table.setStyle(TableStyle(table_styles))

            now_dt = clock.now()
            gen_date_str = custom_footer_date_str or now_dt.strftime("%d-%b-%Y %H:%M IST")
            if reason and reason.lower().replace("_", " ").strip() == "post-lock amendment":
                footer_text = f"Generated {gen_date_str}, revision {revision} (post-lock amendment). Weather data: Open-Meteo.com (CC BY 4.0)"
            else:
                footer_text = f"Generated {gen_date_str}, revision {revision}. Weather data: Open-Meteo.com (CC BY 4.0)"
            if missing_days_count > 0:
                footer_text += f" • {missing_days_count} day(s) not recorded"

            def make_canvas(*args, **kwargs):
                c = NumberedCanvas(*args, **kwargs)
                c.footer_text = footer_text
                return c

            doc.build([pdf_table], canvasmaker=make_canvas)

        atomic_write(dest_file, _write)
        return dest_file
