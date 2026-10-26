"""Review screen state management, effect preview, weather integration, and accept/reject/replace workflows (SPEC B5, B7, AC-03, AC-04, AC-05, AC-12)."""

from datetime import date, datetime
import json
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from app.domain.extraction_models import ExtractionResult
from app.domain.insights import (
    calculate_yield_baseline,
    detect_weather_mismatch,
    evaluate_performance_insight,
)
from app.domain.models import DailyReadingInput, EntryMethod, ReadingStatus, UserRole
from app.domain.totals import calculate_running_totals, find_missing_dates_in_range
from app.domain.weather_models import WeatherQuality, YieldInsight
from app.infra.audit import record_audit_event
from app.infra.clock import Clock
from app.infra.models import CustomerModel, PlantModel, ReadingModel, ReadingRevisionModel, UploadModel
from app.services.reading_service import ReadingService
from app.services.reports.excel import ExcelReportGenerator
from app.services.weather.client import OpenMeteoClient
from app.services.weather.service import WeatherService


class ReviewEffectPreview:
    def __init__(
        self,
        report_date: date,
        computed_inverter_total: float,
        plant_reported_monthly: Optional[float],
        difference_kwh: Optional[float],
        missing_dates: List[date],
        computed_eb_total: float,
        preview_message: str,
        auto_remark: str = "",
        weather_quality: WeatherQuality = WeatherQuality.FINAL,
        weather_mismatch: Tuple[bool, str] = (False, ""),
        performance_insight: Optional[YieldInsight] = None,
        existing_reading_diff: Optional[Dict[str, Tuple[Any, Any]]] = None,
    ) -> None:
        self.report_date = report_date
        self.computed_inverter_total = computed_inverter_total
        self.plant_reported_monthly = plant_reported_monthly
        self.difference_kwh = difference_kwh
        self.missing_dates = missing_dates
        self.computed_eb_total = computed_eb_total
        self.preview_message = preview_message
        self.auto_remark = auto_remark
        self.weather_quality = weather_quality
        self.weather_mismatch = weather_mismatch
        self.performance_insight = performance_insight
        self.existing_reading_diff = existing_reading_diff


class ReviewService:
    def __init__(self, clock: Clock, weather_client: Optional[OpenMeteoClient] = None) -> None:
        self.clock = clock
        self.reading_service = ReadingService(clock)
        self.excel_gen = ExcelReportGenerator()
        self.weather_service = WeatherService(clock, client=weather_client)
        from app.services.month_lifecycle import MonthLifecycleService
        self.month_lifecycle = MonthLifecycleService(clock=clock, weather_client=weather_client)

    def build_effect_preview(
        self,
        session: Session,
        reading_input: DailyReadingInput,
        fetch_weather: bool = True,
    ) -> ReviewEffectPreview:
        """Calculate the prospective effect on monthly totals, gaps, weather remarks, and yield insights."""
        target_date = reading_input.report_date
        year, month = target_date.year, target_date.month

        # Fetch existing active readings for this month excluding this date if updating
        existing_readings = (
            session.query(ReadingModel)
            .filter(
                ReadingModel.report_date >= date(year, month, 1),
                ReadingModel.report_date <= date(year, month, 31),
                ReadingModel.status == ReadingStatus.ACTIVE.value,
                ReadingModel.report_date != target_date,
            )
            .order_by(ReadingModel.report_date.asc())
            .all()
        )

        all_candidate_readings: List[DailyReadingInput] = [
            DailyReadingInput(
                report_date=r.report_date,
                inverter_kwh=r.inverter_kwh,
                eb_export_kwh=r.eb_export_kwh,
                eb_6to10_kwh=r.eb_6to10_kwh,
            )
            for r in existing_readings
        ]
        all_candidate_readings.append(reading_input)

        running_totals = calculate_running_totals(all_candidate_readings)
        target_total = next(t for t in running_totals if t.report_date == target_date)

        recorded_dates = [r.report_date for r in all_candidate_readings]
        missing_dates = find_missing_dates_in_range(
            start_date=date(year, month, 1),
            end_date=target_date,
            recorded_dates=recorded_dates,
        )

        diff_kwh: Optional[float] = None
        plant_monthly = reading_input.reported_monthly_kwh

        if plant_monthly is not None:
            diff_kwh = round(plant_monthly - target_total.running_inverter_total, 2)
            if diff_kwh > 1.0:
                missing_str = ", ".join(str(d.day) for d in missing_dates)
                preview_msg = (
                    f"{target_date.day} {target_date.strftime('%B')}: Monthly Inverter Total becomes "
                    f"{target_total.running_inverter_total:,.2f}. Plant reports {plant_monthly:,.2f}. "
                    f"Difference {diff_kwh:,.0f} kWh = {missing_str} {target_date.strftime('%B')} not yet recorded."
                )
            elif diff_kwh < -1.0:
                preview_msg = (
                    f"Warning: Computed total ({target_total.running_inverter_total:,.2f}) exceeds plant "
                    f"reported ({plant_monthly:,.2f}) by {abs(diff_kwh):,.2f} kWh (possible duplicate/digit error)."
                )
            else:
                preview_msg = (
                    f"Monthly Inverter Total matches plant report: {target_total.running_inverter_total:,.2f} kWh."
                )
        else:
            preview_msg = f"Monthly Inverter Total becomes {target_total.running_inverter_total:,.2f} kWh."

        # Weather enrichment & mismatch
        auto_remark = reading_input.auto_remark or ""
        weather_quality = WeatherQuality.FINAL
        summary_obj = None

        if fetch_weather:
            plant = session.query(PlantModel).first()
            plant_id = plant.id if plant else 1
            auto_remark, weather_quality, summary_obj = self.weather_service.get_or_fetch_weather(
                session=session,
                plant_id=plant_id,
                report_date=target_date,
            )
            # Update candidate reading auto_remark
            reading_input.auto_remark = auto_remark

        weather_mismatch = detect_weather_mismatch(
            plant_weather_text=reading_input.plant_weather_text,
            auto_remark=auto_remark,
        )

        # Performance Insight (yield index)
        performance_insight: Optional[YieldInsight] = None
        inv_val = reading_input.inverter_kwh or 0.0
        if summary_obj and summary_obj.total_solar_energy_kwh_per_m2 > 0:
            plant_id = plant.id if plant else 1
            clear_day_yields = self.weather_service.get_clear_day_yields_history(
                session=session,
                plant_id=plant_id,
                up_to_date=target_date,
            )
            baseline = calculate_yield_baseline(clear_day_yields)
            performance_insight = evaluate_performance_insight(
                report_date=target_date,
                inverter_kwh=inv_val,
                solar_energy_kwh_per_m2=summary_obj.total_solar_energy_kwh_per_m2,
                mean_daytime_cloud_pct=summary_obj.mean_daytime_cloud_pct,
                rain_24h_mm=summary_obj.rain_24h_mm,
                baseline_yield_index=baseline,
            )

        # Existing reading diff (AC-05)
        existing_reading = (
            session.query(ReadingModel)
            .filter_by(report_date=target_date, status=ReadingStatus.ACTIVE.value)
            .first()
        )
        existing_diff: Optional[Dict[str, Tuple[Any, Any]]] = None
        if existing_reading:
            existing_diff = {}
            if existing_reading.inverter_kwh != reading_input.inverter_kwh:
                existing_diff["inverter_kwh"] = (existing_reading.inverter_kwh, reading_input.inverter_kwh)
            if existing_reading.eb_export_kwh != reading_input.eb_export_kwh:
                existing_diff["eb_export_kwh"] = (existing_reading.eb_export_kwh, reading_input.eb_export_kwh)
            if existing_reading.eb_6to10_kwh != reading_input.eb_6to10_kwh:
                existing_diff["eb_6to10_kwh"] = (existing_reading.eb_6to10_kwh, reading_input.eb_6to10_kwh)

        return ReviewEffectPreview(
            report_date=target_date,
            computed_inverter_total=target_total.running_inverter_total,
            plant_reported_monthly=plant_monthly,
            difference_kwh=diff_kwh,
            missing_dates=missing_dates,
            computed_eb_total=target_total.running_eb_total,
            preview_message=preview_msg,
            auto_remark=auto_remark,
            weather_quality=weather_quality,
            weather_mismatch=weather_mismatch,
            performance_insight=performance_insight,
            existing_reading_diff=existing_diff,
        )

    def accept_upload(
        self,
        session: Session,
        upload_id: int,
        reading_input: DailyReadingInput,
        actor_label: str = "Operator",
        role: UserRole = UserRole.OPERATOR,
        override_reason: str = "",
    ) -> ReadingModel:
        """Accept flow: In one database transaction, save reading with weather remarks, mark upload ACCEPTED."""
        upload = session.query(UploadModel).filter_by(id=upload_id).first()
        if not upload:
            raise ValueError(f"Upload {upload_id} not found.")

        reading_input.source_upload_id = upload.id
        reading_input.actor_label = actor_label
        reading_input.entry_method = EntryMethod.IMAGE

        # Ensure weather auto_remark is set if not already provided
        if not reading_input.auto_remark:
            plant = session.query(PlantModel).first()
            plant_id = plant.id if plant else 1
            remark, _, _ = self.weather_service.get_or_fetch_weather(
                session=session,
                plant_id=plant_id,
                report_date=reading_input.report_date,
            )
            reading_input.auto_remark = remark

        reading, _ = self.reading_service.save_reading(
            session=session,
            reading_input=reading_input,
            role=role,
            admin_override_reason=override_reason,
        )

        upload.status = "ACCEPTED"
        session.flush()

        record_audit_event(
            session=session,
            clock=self.clock,
            actor_label=actor_label,
            action="ACCEPT_UPLOAD",
            entity="uploads",
            entity_id=str(upload.id),
            after={"reading_id": reading.id, "report_date": str(reading.report_date)},
            reason=override_reason or "Operator accepted extraction",
        )

        # Trigger month lifecycle handling: workbook rebuild, debounced late-entry PDF or post-lock amendment
        self.month_lifecycle.handle_reading_saved(
            session=session,
            reading_date=reading.report_date,
            role=role,
            actor_label=actor_label,
            admin_reason=override_reason,
        )

        return reading

    def reject_upload(
        self,
        session: Session,
        upload_id: int,
        reason: str,
        actor_label: str = "Operator",
    ) -> None:
        """Reject flow: Mark upload REJECTED with a required reason."""
        upload = session.query(UploadModel).filter_by(id=upload_id).first()
        if not upload:
            raise ValueError(f"Upload {upload_id} not found.")

        upload.status = "REJECTED"
        session.flush()

        record_audit_event(
            session=session,
            clock=self.clock,
            actor_label=actor_label,
            action="REJECT_UPLOAD",
            entity="uploads",
            entity_id=str(upload.id),
            reason=reason,
        )
