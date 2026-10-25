"""CSV importer for historical records, particularly seed/may_2026.csv."""

import csv
from datetime import date, datetime
from pathlib import Path
from typing import List, Tuple
from sqlalchemy.orm import Session
from app.domain.models import DailyReadingInput, EntryMethod, UserRole
from app.infra.clock import Clock
from app.services.reading_service import ReadingService


def parse_date_flexible(val: str) -> date:
    """Parse date from common formats like '5/1/2026', '01/05/2026', '2026-05-01'."""
    val = val.strip()
    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unable to parse date string: '{val}'")


def import_csv_file(
    file_path: Path | str,
    session: Session,
    clock: Clock,
    actor_label: str = "Importer",
    role: UserRole = UserRole.ADMIN,
) -> Tuple[int, List[str]]:
    """Import generation report CSV file into database.
    
    Returns (imported_count, list_of_messages).
    """
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    reading_service = ReadingService(clock)
    imported_count = 0
    messages: List[str] = []

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for line_no, row in enumerate(reader, start=1):
            if not row:
                continue

            first_cell = row[0].strip()
            # Skip empty cells or header labels (e.g. D+1:20ate, Date)
            if not first_cell or any(h in first_cell for h in ("Date", "D+", "Monthly", "Total")):
                continue

            # Try parsing the first cell as a date
            try:
                rep_date = parse_date_flexible(first_cell)
            except ValueError:
                continue  # Not a date row, skip

            # Extract fields with fallback for varying column positions
            # Expected layout:
            # Col 0: Date
            # Col 1: Inverter kWh
            # Col 2: Monthly Inverter Total
            # Col 3: EB Reading
            # Col 4 / 5: EB Reading Total
            # Col 6: 6am-10am
            # Col 7: Remarks
            try:
                inv_val = float(row[1].strip()) if len(row) > 1 and row[1].strip() else 0.0
                rep_monthly = float(row[2].strip()) if len(row) > 2 and row[2].strip() else None
                eb_val = float(row[3].strip()) if len(row) > 3 and row[3].strip() else 0.0

                # 6am-10am is usually in Col 6
                eb_6to10_val = 0.0
                if len(row) > 6 and row[6].strip():
                    eb_6to10_val = float(row[6].strip())

                # Remarks in Col 7 or onwards
                remarks = ""
                if len(row) > 7 and row[7].strip():
                    remarks = row[7].strip()

                reading_input = DailyReadingInput(
                    report_date=rep_date,
                    inverter_kwh=inv_val,
                    eb_export_kwh=eb_val,
                    eb_6to10_kwh=eb_6to10_val,
                    reported_monthly_kwh=rep_monthly,
                    manual_remark=remarks,
                    entry_method=EntryMethod.IMPORT,
                    actor_label=actor_label,
                )

                _, warnings = reading_service.save_reading(
                    session=session,
                    reading_input=reading_input,
                    role=role,
                    admin_override_reason="Historical CSV import",
                )

                imported_count += 1
                if warnings:
                    messages.append(f"Row {line_no} ({rep_date}): {'; '.join(warnings)}")

            except Exception as e:
                messages.append(f"Error on row {line_no} ({first_cell}): {e}")

    return imported_count, messages
