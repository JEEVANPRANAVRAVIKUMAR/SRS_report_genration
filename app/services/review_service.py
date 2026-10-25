"""Review screen state management, effect preview, and accept/reject/replace workflows (SPEC B5, AC-03, AC-04, AC-05)."""

from datetime import date, datetime
import json
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from app.domain.extraction_models import ExtractionResult
from app.domain.models import DailyReadingInput, EntryMethod, ReadingStatus, UserRole
from app.domain.totals import calculate_running_totals, find_missing_dates_in_range
from app.infra.audit import record_audit_event
from app.infra.clock import Clock
from app.infra.models import CustomerModel, ReadingModel, ReadingRevisionModel, UploadModel
from app.services.reading_service import ReadingService
from app.services.reports.excel import ExcelReportGenerator


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
        existing_reading_diff: Optional[Dict[str, Tuple[Any, Any]]] = None,
    ) -> None:
        self.report_date = report_date
        self.computed_inverter_total = computed_inverter_total
        self.plant_reported_monthly = plant_reported_monthly
        self.difference_kwh = difference_kwh
        self.missing_dates = missing_dates
        self.computed_eb_total = computed_eb_total
        self.preview_message = preview_message
        self.existing_reading_diff = existing_reading_diff


class ReviewService:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.reading_service = ReadingService(clock)
        self.excel_gen = ExcelReportGenerator()

    def build_effect_preview(
        self,
        session: Session,
        reading_input: DailyReadingInput,
    ) -> ReviewEffectPreview:
        """Calculate the prospective effect on monthly totals, gaps, and discrepancies (SPEC B5, AC-03)."""
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

        # Merge with this candidate reading
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

        # Compute running totals up to this target date
        running_totals = calculate_running_totals(all_candidate_readings)
        target_total = next(t for t in running_totals if t.report_date == target_date)

        # Find missing dates from day 1 up to target_date
        recorded_dates = [r.report_date for r in all_candidate_readings]
        missing_dates = find_missing_dates_in_range(
            start_date=date(year, month, 1),
            end_date=target_date,
            recorded_dates=recorded_dates,
        )

        diff_kwh: Optional[float] = None
        preview_msg = ""
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

        # Check existing reading diff (AC-05)
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
        """Accept flow: In one database transaction, save reading, record audit, mark upload ACCEPTED."""
        upload = session.query(UploadModel).filter_by(id=upload_id).first()
        if not upload:
            raise ValueError(f"Upload {upload_id} not found.")

        reading_input.source_upload_id = upload.id
        reading_input.actor_label = actor_label
        reading_input.entry_method = EntryMethod.IMAGE

        # 1. Upsert reading with revision tracking and audit logging
        reading, _ = self.reading_service.save_reading(
            session=session,
            reading_input=reading_input,
            role=role,
            admin_override_reason=override_reason,
        )

        # 2. Mark upload ACCEPTED
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
