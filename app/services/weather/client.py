"""Open-Meteo API client supporting historical archive, recent forecast, retries, and test fake (SPEC B7, AC-12)."""

from abc import ABC, abstractmethod
from datetime import date, datetime, time, timedelta
import json
import logging
from typing import Any, Dict, Optional, Tuple
import urllib.parse
import urllib.request
from app.domain.insights import compute_daytime_metrics
from app.domain.weather_models import DaytimeWeatherSummary, WeatherQuality
from app.infra.clock import Clock
from app.infra.settings import settings

logger = logging.getLogger(__name__)

# Official Endpoints
FREE_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FREE_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
COMMERCIAL_ARCHIVE_URL = "https://customer-archive-api.open-meteo.com/v1/archive"
COMMERCIAL_FORECAST_URL = "https://customer-api.open-meteo.com/v1/forecast"

HOURLY_VARIABLES = "temperature_2m,cloud_cover,precipitation,shortwave_radiation,weather_code"


class WeatherClientError(Exception):
    """Raised when weather API call fails after retries."""
    pass


class OpenMeteoClient(ABC):
    """Abstract interface for Open-Meteo weather client."""

    @abstractmethod
    def fetch_weather(
        self,
        latitude: float,
        longitude: float,
        report_date: date,
        clock: Clock,
    ) -> DaytimeWeatherSummary:
        """Fetch and summarize weather for report_date at (latitude, longitude)."""
        pass


class RealOpenMeteoClient(OpenMeteoClient):
    """Real HTTP client calling Open-Meteo API with timeout and retries."""

    def __init__(self, api_key: Optional[str] = None, timeout_seconds: float = 10.0, max_retries: int = 3) -> None:
        self.api_key = api_key or settings.OPEN_METEO_API_KEY
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    def get_endpoint_and_params(
        self,
        latitude: float,
        longitude: float,
        report_date: date,
        clock: Clock,
    ) -> Tuple[str, Dict[str, Any]]:
        """Determine whether to use archive or forecast endpoint and assemble query parameters."""
        today = clock.today()
        days_ago = (today - report_date).days

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "timezone": settings.TIMEZONE,
            "hourly": HOURLY_VARIABLES,
        }

        if self.api_key:
            params["apikey"] = self.api_key
            archive_base = COMMERCIAL_ARCHIVE_URL
            forecast_base = COMMERCIAL_FORECAST_URL
        else:
            archive_base = FREE_ARCHIVE_URL
            forecast_base = FREE_FORECAST_URL

        # SPEC B7: For dates older than 7 days use archive; for last 7 days use forecast
        if days_ago > 7:
            endpoint = archive_base
            date_str = report_date.isoformat()
            params["start_date"] = date_str
            params["end_date"] = date_str
        else:
            endpoint = forecast_base
            date_str = report_date.isoformat()
            params["start_date"] = date_str
            params["end_date"] = date_str

        return endpoint, params

    def determine_quality(self, report_date: date, clock: Clock) -> WeatherQuality:
        """SPEC B7: Day is PROVISIONAL if within last 7 days or fetched before 20:00 IST on that same day."""
        today = clock.today()
        now = clock.now()

        days_ago = (today - report_date).days
        if days_ago <= 7:
            return WeatherQuality.PROVISIONAL
        if report_date == today and now.hour < 20:
            return WeatherQuality.PROVISIONAL
        return WeatherQuality.FINAL

    def fetch_weather(
        self,
        latitude: float,
        longitude: float,
        report_date: date,
        clock: Clock,
    ) -> DaytimeWeatherSummary:
        endpoint, params = self.get_endpoint_and_params(latitude, longitude, report_date, clock)
        query_string = urllib.parse.urlencode(params)
        full_url = f"{endpoint}?{query_string}"

        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(
                    full_url,
                    headers={"User-Agent": "SRS-Solar-Daily-Log/1.0"},
                )
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                    raw_data = json.loads(response.read().decode("utf-8"))

                hourly = raw_data.get("hourly", {})
                temps = hourly.get("temperature_2m", [])
                clouds = hourly.get("cloud_cover", [])
                rains = hourly.get("precipitation", [])
                radiations = hourly.get("shortwave_radiation", [])
                weather_codes = hourly.get("weather_code", [])

                quality = self.determine_quality(report_date, clock)
                return compute_daytime_metrics(
                    report_date=report_date,
                    temperatures_2m=temps,
                    cloud_covers_pct=clouds,
                    precipitations_mm=rains,
                    shortwave_radiations_w_m2=radiations,
                    quality=quality,
                    raw_response=raw_data,
                )
            except Exception as e:
                last_error = e
                logger.warning(f"Open-Meteo fetch attempt {attempt}/{self.max_retries} failed: {e}")

        raise WeatherClientError(f"Open-Meteo service unreachable after {self.max_retries} retries: {last_error}")


class FakeOpenMeteoClient(OpenMeteoClient):
    """Deterministic Fake Open-Meteo client for offline testing and AC-12 validation."""

    def __init__(
        self,
        should_fail: bool = False,
        fixed_cloud_pct: float = 15.0,
        fixed_rain_mm: float = 0.0,
        fixed_max_temp_c: float = 35.0,
        fixed_radiation_w_m2: float = 650.0,  # ~7.8 kWh/m2 across 12 hours
        forced_quality: Optional[WeatherQuality] = None,
    ) -> None:
        self.should_fail = should_fail
        self.fixed_cloud_pct = fixed_cloud_pct
        self.fixed_rain_mm = fixed_rain_mm
        self.fixed_max_temp_c = fixed_max_temp_c
        self.fixed_radiation_w_m2 = fixed_radiation_w_m2
        self.forced_quality = forced_quality
        self.last_endpoint_called: Optional[str] = None
        self.last_params: Optional[Dict[str, Any]] = None
        self.call_count = 0

    def fetch_weather(
        self,
        latitude: float,
        longitude: float,
        report_date: date,
        clock: Clock,
    ) -> DaytimeWeatherSummary:
        self.call_count += 1
        today = clock.today()
        days_ago = (today - report_date).days

        # Track endpoint routing for verification
        if days_ago > 7:
            self.last_endpoint_called = FREE_ARCHIVE_URL
        else:
            self.last_endpoint_called = FREE_FORECAST_URL

        self.last_params = {
            "latitude": latitude,
            "longitude": longitude,
            "report_date": report_date.isoformat(),
            "days_ago": days_ago,
        }

        if self.should_fail:
            raise WeatherClientError("Open-Meteo service is currently down (simulated 503).")

        # Determine quality
        if self.forced_quality is not None:
            quality = self.forced_quality
        else:
            quality = WeatherQuality.PROVISIONAL if days_ago <= 7 else WeatherQuality.FINAL

        # Synthesize 24 hourly readings
        hourly_temps = [self.fixed_max_temp_c - 5.0] * 6 + [self.fixed_max_temp_c] * 12 + [self.fixed_max_temp_c - 4.0] * 6
        hourly_clouds = [self.fixed_cloud_pct] * 24
        hourly_rains = [self.fixed_rain_mm / 24.0] * 24
        hourly_radiations = [0.0] * 6 + [self.fixed_radiation_w_m2] * 12 + [0.0] * 6

        return compute_daytime_metrics(
            report_date=report_date,
            temperatures_2m=hourly_temps,
            cloud_covers_pct=hourly_clouds,
            precipitations_mm=hourly_rains,
            shortwave_radiations_w_m2=hourly_radiations,
            quality=quality,
            raw_response={"simulated": True, "provider": "fake-open-meteo"},
        )
