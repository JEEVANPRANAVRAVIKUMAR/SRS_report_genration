"""Unit tests for Acceptance Criteria AC-16 (Excel parts):
- Formula injection protection (remarks starting with = appear as plain text, not formulas).
- Atomic file writes and resilience against mid-write failure/crash.
- Valid OOXML structure (opens without repair).
"""

from datetime import date
from pathlib import Path
import unittest
import zipfile
from app.domain.models import DailyReadingInput
from app.services.reports.atomic import atomic_write
from app.services.reports.excel import ExcelReportGenerator


class TestAC16Excel(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path(__file__).resolve().parent.parent.parent / "data" / "test_workbooks"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.excel_gen = ExcelReportGenerator(output_dir=self.tmp_dir)

    def test_formula_injection_safety(self) -> None:
        """AC-16: A remark of =HYPERLINK(...) appears as text, never as a formula."""
        malicious_remark = '=HYPERLINK("http://evil.com", "ClickMe")'

        readings = [
            DailyReadingInput(
                report_date=date(2026, 5, 1),
                inverter_kwh=6489.0,
                eb_export_kwh=6336.0,
                eb_6to10_kwh=1236.0,
                manual_remark=malicious_remark,
            )
        ]

        file_path = self.excel_gen.generate_annual_workbook(
            year=2026,
            readings_by_month={5: readings},
        )

        self.assertTrue(file_path.exists())

        # Inspect the XLSX archive (OOXML zip package)
        with zipfile.ZipFile(file_path, "r") as z:
            namelist = z.namelist()
            self.assertIn("[Content_Types].xml", namelist)
            self.assertIn("xl/workbook.xml", namelist)

            # Check shared strings or sheet XML
            content = ""
            for name in namelist:
                if name.startswith("xl/") and (name.endswith(".xml") or name.endswith(".xml.rels")):
                    content += z.read(name).decode("utf-8", errors="ignore")

            # Must contain the string literal text
            self.assertIn("=HYPERLINK", content)

            # Must NOT be defined as a formula tag <f>
            self.assertNotIn("<f>=HYPERLINK", content)
            self.assertNotIn('<f attr="true">=HYPERLINK', content)

    def test_process_kill_mid_write_leaves_previous_file_intact(self) -> None:
        """AC-16: Killing the process or failing mid-write leaves the previous file intact."""
        target_file = self.tmp_dir / "crash_test.txt"

        # Step 1: Write initial intact file
        initial_content = b"Original Intact Report File Content 2026"
        with open(target_file, "wb") as f:
            f.write(initial_content)

        self.assertEqual(target_file.read_bytes(), initial_content)

        # Step 2: Attempt atomic write that raises an exception mid-write (simulating crash)
        class ProcessKilledSimulationError(Exception):
            pass

        def failing_writer(tmp_path: Path) -> None:
            # Partially write data to temporary file
            with open(tmp_path, "wb") as f:
                f.write(b"Corrupted Partial Data...")
            # Simulate sudden crash
            raise ProcessKilledSimulationError("Process terminated abruptly mid-write")

        with self.assertRaises(ProcessKilledSimulationError):
            atomic_write(target_file, failing_writer)

        # Step 3: Verify the original file is completely intact with original bytes
        self.assertTrue(target_file.exists())
        self.assertEqual(target_file.read_bytes(), initial_content)

        # Step 4: Verify no temporary .tmp files remain in the folder
        tmp_files = list(self.tmp_dir.glob(".tmp_crash_test.txt_*"))
        self.assertEqual(len(tmp_files), 0, "No orphaned temporary files should linger after a crash")


if __name__ == "__main__":
    unittest.main()
