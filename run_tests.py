"""Self-contained test runner executing all Phase P1, P2, P3, and P4 unit test suites."""

import sys
import unittest
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Phase P1 Test Suites
from tests.unit.test_ac02_seed_import import TestAC02SeedImport
from tests.unit.test_ac14_validation_rules import TestAC14ValidationRules
from tests.unit.test_ac17_calendar_months import TestAC17CalendarMonths
from tests.unit.test_ac18_weather_classification import TestAC18WeatherClassification
from tests.unit.test_clock_and_audit import TestClockAndAudit

# Phase P2 Test Suites
from tests.unit.test_ac06_pdf_sample import TestAC06PDFSample
from tests.unit.test_ac16_excel import TestAC16Excel

# Phase P3 Test Suites
from tests.unit.test_ac01_extraction import TestAC01Extraction
from tests.unit.test_ac03_ac04_monthly_gaps import TestAC03AC04MonthlyGaps
from tests.unit.test_ac05_duplicate_replace import TestAC05DuplicateReplace
from tests.unit.test_ac13_bad_inputs import TestAC13BadInputs
from tests.unit.test_ac15_privacy import TestAC15Privacy

# Phase P4 Test Suites
from tests.unit.test_ac12_weather_failure_and_refresh import TestAC12WeatherFailureAndRefresh
from tests.unit.test_open_meteo_archive_routing import TestOpenMeteoArchiveRouting
from tests.unit.test_yield_insights import TestYieldInsights

# Phase P5 Test Suites
from tests.unit.test_ac07_month_close import TestAC07MonthClose
from tests.unit.test_ac08_late_entry_debounce import TestAC08LateEntryDebounce
from tests.unit.test_ac09_catchup_startup import TestAC09CatchupStartup
from tests.unit.test_ac10_month_locking import TestAC10MonthLocking
from tests.unit.test_ac11_utc_clock_close import TestAC11UTCClockClose

# Phase P6 Test Suites
from tests.unit.test_ac19_backup_restore import TestAC19BackupRestore
from tests.unit.test_ac20_security_csrf_rbac import TestAC20SecurityCSRFRBAC


def run_all_tests() -> bool:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Phase P1
    suite.addTests(loader.loadTestsFromTestCase(TestAC02SeedImport))
    suite.addTests(loader.loadTestsFromTestCase(TestAC14ValidationRules))
    suite.addTests(loader.loadTestsFromTestCase(TestAC17CalendarMonths))
    suite.addTests(loader.loadTestsFromTestCase(TestAC18WeatherClassification))
    suite.addTests(loader.loadTestsFromTestCase(TestClockAndAudit))

    # Phase P2
    suite.addTests(loader.loadTestsFromTestCase(TestAC06PDFSample))
    suite.addTests(loader.loadTestsFromTestCase(TestAC16Excel))

    # Phase P3
    suite.addTests(loader.loadTestsFromTestCase(TestAC01Extraction))
    suite.addTests(loader.loadTestsFromTestCase(TestAC03AC04MonthlyGaps))
    suite.addTests(loader.loadTestsFromTestCase(TestAC05DuplicateReplace))
    suite.addTests(loader.loadTestsFromTestCase(TestAC13BadInputs))
    suite.addTests(loader.loadTestsFromTestCase(TestAC15Privacy))

    # Phase P4
    suite.addTests(loader.loadTestsFromTestCase(TestAC12WeatherFailureAndRefresh))
    suite.addTests(loader.loadTestsFromTestCase(TestOpenMeteoArchiveRouting))
    suite.addTests(loader.loadTestsFromTestCase(TestYieldInsights))

    # Phase P5
    suite.addTests(loader.loadTestsFromTestCase(TestAC07MonthClose))
    suite.addTests(loader.loadTestsFromTestCase(TestAC08LateEntryDebounce))
    suite.addTests(loader.loadTestsFromTestCase(TestAC09CatchupStartup))
    suite.addTests(loader.loadTestsFromTestCase(TestAC10MonthLocking))
    suite.addTests(loader.loadTestsFromTestCase(TestAC11UTCClockClose))

    # Phase P6
    suite.addTests(loader.loadTestsFromTestCase(TestAC19BackupRestore))
    suite.addTests(loader.loadTestsFromTestCase(TestAC20SecurityCSRFRBAC))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
