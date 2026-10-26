"""Unit tests for Open-Meteo routing:
Re-tests May 2026 dates through the historical archive path (SPEC B7).
"""

from datetime import date
import unittest
from app.domain.weather_models import WeatherQuality
from app.infra.clock import FakeClock
from app.services.weather.client import (
    COMMERCIAL_ARCHIVE_URL,
    COMMERCIAL_FORECAST_URL,
    FREE_ARCHIVE_URL,
    FREE_FORECAST_URL,
    FakeOpenMeteoClient,
    RealOpenMeteoClient,
)


class TestOpenMeteoArchiveRouting(unittest.TestCase):
    def test_may_2026_dates_route_through_archive_path(self) -> None:
        """May 2026 dates older than 7 days must use the historical archive endpoint."""
        # Clock set to June 1, 2026 (or present)
        clock = FakeClock(date(2026, 6, 1))
        client = RealOpenMeteoClient(api_key=None)

        may_dates = [
            date(2026, 5, 1),
            date(2026, 5, 8),
            date(2026, 5, 18),
            date(2026, 5, 22),
        ]

        for d in may_dates:
            endpoint, params = client.get_endpoint_and_params(
                latitude=10.851319,
                longitude=77.909541,
                report_date=d,
                clock=clock,
            )

            # Must route to archive endpoint
            self.assertEqual(
                endpoint,
                FREE_ARCHIVE_URL,
                f"Date {d} is older than 7 days and must route to archive endpoint!",
            )
            self.assertEqual(params["start_date"], d.isoformat())
            self.assertEqual(params["end_date"], d.isoformat())
            self.assertEqual(params["timezone"], "Asia/Kolkata")
            self.assertIn("shortwave_radiation", params["hourly"])

            # Quality must be FINAL
            quality = client.determine_quality(d, clock)
            self.assertEqual(quality, WeatherQuality.FINAL)

    def test_recent_date_within_7_days_routes_through_forecast(self) -> None:
        """Dates within 7 days must route to forecast endpoint and be PROVISIONAL."""
        # Clock set to 24 May 2026, report date is 22 May 2026 (2 days ago <= 7)
        clock = FakeClock(date(2026, 5, 24))
        client = RealOpenMeteoClient(api_key=None)

        endpoint, params = client.get_endpoint_and_params(
            latitude=10.851319,
            longitude=77.909541,
            report_date=date(2026, 5, 22),
            clock=clock,
        )

        self.assertEqual(endpoint, FREE_FORECAST_URL)
        quality = client.determine_quality(date(2026, 5, 22), clock)
        self.assertEqual(quality, WeatherQuality.PROVISIONAL)

    def test_commercial_host_routing_when_api_key_set(self) -> None:
        """When OPEN_METEO_API_KEY is configured, use commercial host and pass apikey."""
        clock = FakeClock(date(2026, 6, 1))
        client = RealOpenMeteoClient(api_key="secret-commercial-key-123")

        endpoint, params = client.get_endpoint_and_params(
            latitude=10.851319,
            longitude=77.909541,
            report_date=date(2026, 5, 22),
            clock=clock,
        )

        self.assertEqual(endpoint, COMMERCIAL_ARCHIVE_URL)
        self.assertEqual(params["apikey"], "secret-commercial-key-123")

    def test_fake_client_tracks_archive_call(self) -> None:
        """FakeOpenMeteoClient accurately mirrors routing logic for tests."""
        clock = FakeClock(date(2026, 6, 1))
        fake_client = FakeOpenMeteoClient()

        summary = fake_client.fetch_weather(
            latitude=10.851319,
            longitude=77.909541,
            report_date=date(2026, 5, 22),
            clock=clock,
        )

        self.assertEqual(fake_client.last_endpoint_called, FREE_ARCHIVE_URL)
        self.assertEqual(summary.quality, WeatherQuality.FINAL)
        self.assertGreater(summary.total_solar_energy_kwh_per_m2, 0.0)


if __name__ == "__main__":
    unittest.main()
