"""Weather service managing caching, retries, pending state, and quality transitions (SPEC B7, AC-12)."""

from datetime import date, datetime
import json
import logging
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from app.domain.insights import compute_yield_index, is_clear_day
from app.domain.weather_models import DaytimeWeatherSummary, WeatherQuality
from app.infra.audit import record_audit_event
from app.infra.clock import Clock
from app.infra.models import PlantModel, ReadingModel, WeatherDailyModel
from app.infra.settings import settings
from app.services.weather.client import (
    OpenMeteoClient,
    RealOpenMeteoClient,
    WeatherClientError,
)

logger = logging.getLogger(__name__)


class WeatherService:
    def __init__(self, clock: Clock, client: Optional[OpenMeteoClient] = None) -> None:
        self.clock = clock
        self.client = client or RealOpenMeteoClient()

    def get_or_fetch_weather(
        self,
        session: Session,
        plant_id: int,
        report_date: date,
        force_refresh: bool = False,
    ) -> Tuple[str, WeatherQuality, Optional[DaytimeWeatherSummary]]:
        """Fetch weather for report_date.
        
        Returns (auto_remark, quality, weather_summary).
        If service is down, returns ('Weather pending', PROVISIONAL, None) without crashing.
        """
        # 1. Check local cache in database
        existing = (
            session.query(WeatherDailyModel)
            .filter_by(plant_id=plant_id, date=report_date)
            .first()
        )

        if existing and not force_refresh:
            # If already FINAL, return cached
            if existing.quality == WeatherQuality.FINAL.value and existing.remark_text != "Weather pending":
                return existing.remark_text or "", WeatherQuality.FINAL, None

        # 2. Fetch from Open-Meteo
        plant = session.query(PlantModel).filter_by(id=plant_id).first()
        lat = plant.latitude if plant else settings.PLANT_LATITUDE
        lon = plant.longitude if plant else settings.PLANT_LONGITUDE

        try:
            summary = self.client.fetch_weather(
                latitude=lat,
                longitude=lon,
                report_date=report_date,
                clock=self.clock,
            )

            metrics_json = json.dumps({
                "mean_daytime_cloud_pct": summary.mean_daytime_cloud_pct,
                "total_solar_energy_kwh_per_m2": summary.total_solar_energy_kwh_per_m2,
                "morning_mean_cloud_pct": summary.morning_mean_cloud_pct,
                "morning_solar_energy_kwh_per_m2": summary.morning_solar_energy_kwh_per_m2,
                "rain_24h_mm": summary.rain_24h_mm,
                "max_temperature_c": summary.max_temperature_c,
            })
            raw_json = json.dumps(summary.raw_response or {})

            if existing:
                existing.quality = summary.quality.value
                existing.fetched_at = self.clock.now().replace(tzinfo=None)
                existing.metrics = metrics_json
                existing.sky_class = summary.sky_class
                existing.rain_class = summary.rain_class or ""
                existing.remark_text = summary.auto_remark
                existing.raw_response = raw_json
            else:
                new_entry = WeatherDailyModel(
                    plant_id=plant_id,
                    date=report_date,
                    provider=summary.provider,
                    quality=summary.quality.value,
                    fetched_at=self.clock.now().replace(tzinfo=None),
                    metrics=metrics_json,
                    sky_class=summary.sky_class,
                    rain_class=summary.rain_class or "",
                    remark_text=summary.auto_remark,
                    raw_response=raw_json,
                )
                session.add(new_entry)

            session.flush()
            return summary.auto_remark, summary.quality, summary

        except WeatherClientError as e:
            # AC-12: If service is down, save reading with remark 'Weather pending', do not crash
            logger.warning(f"Weather service down for {report_date}: {e}")
            pending_remark = "Weather pending"
            quality = WeatherQuality.PROVISIONAL

            if existing:
                existing.quality = quality.value
                existing.remark_text = pending_remark
                existing.fetched_at = self.clock.now().replace(tzinfo=None)
            else:
                pending_entry = WeatherDailyModel(
                    plant_id=plant_id,
                    date=report_date,
                    provider="open-meteo",
                    quality=quality.value,
                    fetched_at=self.clock.now().replace(tzinfo=None),
                    remark_text=pending_remark,
                    raw_response=json.dumps({"error": str(e), "status": "down"}),
                )
                session.add(pending_entry)

            session.flush()
            return pending_remark, quality, None

    def refresh_provisional_weather(
        self,
        session: Session,
        plant_id: int,
    ) -> List[date]:
        """Nightly / maintenance job to refresh all PROVISIONAL or pending days.
        
        AC-12: Provisional weather is replaced by final data after 7 days and remark updates.
        """
        provisional_entries = (
            session.query(WeatherDailyModel)
            .filter(
                WeatherDailyModel.plant_id == plant_id,
                WeatherDailyModel.quality == WeatherQuality.PROVISIONAL.value,
            )
            .all()
        )

        refreshed_dates: List[date] = []
        for entry in provisional_entries:
            remark, quality, summary = self.get_or_fetch_weather(
                session=session,
                plant_id=plant_id,
                report_date=entry.date,
                force_refresh=True,
            )

            # Update associated reading's auto_remark if it changed
            reading = session.query(ReadingModel).filter_by(report_date=entry.date).first()
            if reading and reading.auto_remark != remark:
                old_remark = reading.auto_remark
                reading.auto_remark = remark
                reading.updated_at = self.clock.now().replace(tzinfo=None)
                record_audit_event(
                    session=session,
                    clock=self.clock,
                    actor_label="Weather Service",
                    action="UPDATE_WEATHER_REMARK",
                    entity="readings",
                    entity_id=str(reading.id),
                    before={"auto_remark": old_remark},
                    after={"auto_remark": remark, "quality": quality.value},
                    reason="Provisional weather finalized",
                )
            refreshed_dates.append(entry.date)

        session.commit()
        return refreshed_dates

    def get_clear_day_yields_history(
        self,
        session: Session,
        plant_id: int,
        up_to_date: date,
        limit: int = 30,
    ) -> List[float]:
        """Fetch historical yield indices on clear days up to up_to_date for baseline calculation."""
        records = (
            session.query(ReadingModel, WeatherDailyModel)
            .join(WeatherDailyModel, ReadingModel.report_date == WeatherDailyModel.date)
            .filter(
                ReadingModel.report_date < up_to_date,
                ReadingModel.status == "ACTIVE",
            )
            .order_by(ReadingModel.report_date.asc())
            .all()
        )

        clear_yields: List[float] = []
        for reading, weather in records:
            if not weather.metrics:
                continue
            try:
                metrics = json.loads(weather.metrics)
                cloud = metrics.get("mean_daytime_cloud_pct", 100.0)
                rain = metrics.get("rain_24h_mm", 100.0)
                solar_kwh = metrics.get("total_solar_energy_kwh_per_m2", 0.0)

                if is_clear_day(cloud, rain) and solar_kwh > 0:
                    y_idx = compute_yield_index(reading.inverter_kwh, solar_kwh)
                    clear_yields.append(y_idx)
            except Exception:
                continue

        return clear_yields[-limit:]
