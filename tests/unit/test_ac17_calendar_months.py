"""Unit tests for Acceptance Criteria AC-17:
Months with 28, 29, 30 and 31 days render the right number of rows (test February 2027, February 2028, April and May).
"""

from datetime import date
import unittest
from app.domain.months import get_month_calendar_dates, get_month_days_count


class TestAC17CalendarMonths(unittest.TestCase):
    def test_february_2027_28_days(self) -> None:
        """February 2027 is a standard year (28 days)."""
        days = get_month_days_count(2027, 2)
        self.assertEqual(days, 28)
        calendar_dates = get_month_calendar_dates(2027, 2)
        self.assertEqual(len(calendar_dates), 28)
        self.assertEqual(calendar_dates[0], date(2027, 2, 1))
        self.assertEqual(calendar_dates[-1], date(2027, 2, 28))

    def test_february_2028_29_days_leap_year(self) -> None:
        """February 2028 is a leap year (29 days)."""
        days = get_month_days_count(2028, 2)
        self.assertEqual(days, 29)
        calendar_dates = get_month_calendar_dates(2028, 2)
        self.assertEqual(len(calendar_dates), 29)
        self.assertEqual(calendar_dates[0], date(2028, 2, 1))
        self.assertEqual(calendar_dates[-1], date(2028, 2, 29))

    def test_april_30_days(self) -> None:
        """April has 30 days."""
        days = get_month_days_count(2026, 4)
        self.assertEqual(days, 30)
        calendar_dates = get_month_calendar_dates(2026, 4)
        self.assertEqual(len(calendar_dates), 30)
        self.assertEqual(calendar_dates[0], date(2026, 4, 1))
        self.assertEqual(calendar_dates[-1], date(2026, 4, 30))

    def test_may_31_days(self) -> None:
        """May has 31 days."""
        days = get_month_days_count(2026, 5)
        self.assertEqual(days, 31)
        calendar_dates = get_month_calendar_dates(2026, 5)
        self.assertEqual(len(calendar_dates), 31)
        self.assertEqual(calendar_dates[0], date(2026, 5, 1))
        self.assertEqual(calendar_dates[-1], date(2026, 5, 31))


if __name__ == "__main__":
    unittest.main()
