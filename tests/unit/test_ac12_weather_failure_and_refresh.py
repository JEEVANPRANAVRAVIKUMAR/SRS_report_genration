"""Unit tests for Acceptance Criteria AC-12:
Weather service down: the reading is saved, the remark says 'Weather pending',
retries run, nothing crashes. Provisional weather is replaced by final data after
7 days and the remark updates.
"""

from datetime import date, timedelta
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.domain.models import DailyReadingInput, EntryMethod
from app.domain.weather_models import WeatherQuality
from app.infra.clock import FakeClock
from app.infra.db import init_db
from app.infra.models import AuditLogModel, Base, ReadingModel, WeatherDailyModel
from app.services.reading_service import ReadingService
from app.services.review_service import ReviewService
from app.services.weather.client import FakeOpenMeteoClient
from app.services.weather.service import WeatherService


class TestAC12WeatherFailureAndRefresh(unittest.TestCase):
    def setUp(self) -> None:
        self.report_date = date(2026, 5, 22)
        # Clock initially set to the report date
        self.clock = FakeClock(self.report_date)

        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        init_db(engine_override=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def test_weather_service_down_saves_reading_with_weather_pending_and_refreshes(self) -> None:
        """AC-12: Outage leaves 'Weather pending', 7-day advance finalizes and updates remark."""
        # 1. Setup simulated weather outage (should_fail=True)
        failing_client = FakeOpenMeteoClient(should_fail=True)
        weather_service = WeatherService(self.clock, client=failing_client)
        reading_service = ReadingService(self.clock)

        with self.Session() as session:
            # Fetch weather during outage
            remark, quality, summary = weather_service.get_or_fetch_weather(
                session=session,
                plant_id=1,
                report_date=self.report_date,
            )

            # Assertions for outage state
            self.assertEqual(remark, "Weather pending")
            self.assertEqual(quality, WeatherQuality.PROVISIONAL)
            self.assertIsNone(summary)

            # Save the daily reading with 'Weather pending'
            reading_input = DailyReadingInput(
                report_date=self.report_date,
                inverter_kwh=7625.0,
                eb_export_kwh=7452.0,
                eb_6to10_kwh=1584.0,
                auto_remark=remark,
                entry_method=EntryMethod.IMAGE,
                actor_label="Operator",
            )
            reading, _ = reading_service.save_reading(session, reading_input)
            session.commit()

            # Verify persisted reading has 'Weather pending' and did not crash
            saved_reading = session.query(ReadingModel).filter_by(report_date=self.report_date).first()
            self.assertIsNotNone(saved_reading)
            self.assertEqual(saved_reading.auto_remark, "Weather pending")

            weather_entry = session.query(WeatherDailyModel).filter_by(date=self.report_date).first()
            self.assertIsNotNone(weather_entry)
            self.assertEqual(weather_entry.quality, WeatherQuality.PROVISIONAL.value)
            self.assertEqual(weather_entry.remark_text, "Weather pending")

        # 2. Advance clock past 7 days (e.g. 10 days later: 2026-06-01)
        self.clock.advance(timedelta(days=10))

        # Weather service is now online and returns finalized sunny weather
        online_client = FakeOpenMeteoClient(
            should_fail=False,
            fixed_cloud_pct=15.0,
            fixed_rain_mm=0.0,
            fixed_max_temp_c=35.0,
            forced_quality=WeatherQuality.FINAL,
        )
        refreshing_weather_service = WeatherService(self.clock, client=online_client)

        with self.Session() as session:
            refreshed_dates = refreshing_weather_service.refresh_provisional_weather(session, plant_id=1)
            self.assertIn(self.report_date, refreshed_dates)

            # Verify that reading was updated from 'Weather pending' to 'Sunny, 35°C'
            updated_reading = session.query(ReadingModel).filter_by(report_date=self.report_date).first()
            self.assertIsNotNone(updated_reading)
            self.assertEqual(updated_reading.auto_remark, "Sunny, 35°C")

            # Verify weather_daily is now FINAL
            updated_weather = session.query(WeatherDailyModel).filter_by(date=self.report_date).first()
            self.assertEqual(updated_weather.quality, WeatherQuality.FINAL.value)
            self.assertEqual(updated_weather.remark_text, "Sunny, 35°C")

            # Verify audit trail recorded UPDATE_WEATHER_REMARK
            audit_entry = (
                session.query(AuditLogModel)
                .filter_by(action="UPDATE_WEATHER_REMARK")
                .first()
            )
            self.assertIsNotNone(audit_entry)
            self.assertIn("Weather pending", audit_entry.before)
            self.assertIn("Sunny, 35°C", audit_entry.after)


if __name__ == "__main__":
    unittest.main()
