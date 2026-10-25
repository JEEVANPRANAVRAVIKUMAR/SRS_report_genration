"""Service layer for saving, validating, and retrieving daily solar readings."""

from datetime import date, datetime
import json
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from app.domain.models import (
    DailyReadingInput,
    DailyTotals,
    EntryMethod,
    MonthStatus,
    ReadingStatus,
    UserRole,
)
from app.domain.months import determine_month_status
from app.domain.totals import calculate_running_totals
from app.domain.validation import validate_reading
from app.infra.audit import record_audit_event
from app.infra.clock import Clock
from app.infra.models import (
    CustomerModel,
    MonthModel,
    ReadingModel,
    ReadingRevisionModel,
)
from app.infra.settings import settings


class ReadingService:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock

    def get_target_customer(self, session: Session) -> CustomerModel:
        """Fetch the single target customer (SRS KUMARAN)."""
        customer = (
            session.query(CustomerModel)
            .filter_by(is_target=True)
            .first()
        )
        if not customer:
            raise ValueError("Target customer 'M/s. SRS KUMARAN INDIA PVT LTD' not found in database.")
        return customer

    def get_or_create_month(
        self,
        session: Session,
        customer_id: int,
        year: int,
        month: int,
    ) -> MonthModel:
        """Get or initialize the MonthModel record for a given YM."""
        ym = f"{year:04d}-{month:02d}"
        month_record = (
            session.query(MonthModel)
            .filter_by(customer_id=customer_id, ym=ym)
            .first()
        )
        if not month_record:
            status = determine_month_status(
                year=year,
                month=month,
                current_time=self.clock.now(),
                close_time_str=settings.CLOSE_TIME,
                grace_days=settings.GRACE_DAYS,
            )
            month_record = MonthModel(
                customer_id=customer_id,
                ym=ym,
                status=status.value,
                pdf_revision=1,
            )
            session.add(month_record)
            session.flush()
        return month_record

    def save_reading(
        self,
        session: Session,
        reading_input: DailyReadingInput,
        role: UserRole = UserRole.OPERATOR,
        admin_override_reason: str = "",
        skip_validation: bool = False,
    ) -> Tuple[ReadingModel, List[str]]:
        """Save or update a daily reading in one atomic database transaction.
        
        Returns (reading_model, list_of_warning_messages).
        """
        customer = self.get_target_customer(session)
        rep_date = reading_input.report_date
        month_record = self.get_or_create_month(session, customer.id, rep_date.year, rep_date.month)

        # Check permissions based on month status
        month_status = MonthStatus(month_record.status)
        if month_status == MonthStatus.LOCKED:
            if role != UserRole.ADMIN or not admin_override_reason.strip():
                raise PermissionError(
                    f"Month {month_record.ym} is LOCKED. Only an Admin with a written reason can modify it."
                )

        warnings_list: List[str] = []

        # Run validation
        if not skip_validation:
            # Calculate existing month-to-date up to this date
            existing_month_readings = (
                session.query(ReadingModel)
                .filter(
                    ReadingModel.customer_id == customer.id,
                    ReadingModel.report_date >= date(rep_date.year, rep_date.month, 1),
                    ReadingModel.report_date <= rep_date,
                    ReadingModel.status == ReadingStatus.ACTIVE.value,
                )
                .all()
            )
            current_month_inv_sum = sum(
                r.inverter_kwh for r in existing_month_readings if r.report_date < rep_date
            ) + (reading_input.inverter_kwh or 0.0)

            val_report = validate_reading(
                reading=reading_input,
                computed_month_to_date_inverter=current_month_inv_sum,
                eb_mf=settings.EB_MF,
                max_daily_inverter_kwh=settings.MAX_DAILY_INVERTER_KWH,
                inverter_spike_ratio=settings.INVERTER_SPIKE_RATIO,
                eb_ratio_min=settings.EB_RATIO_MIN,
                eb_ratio_max=settings.EB_RATIO_MAX,
            )

            is_admin = (role == UserRole.ADMIN)
            if not val_report.can_accept(is_admin=is_admin, admin_override_reason=admin_override_reason):
                err_msgs = [e.message for e in val_report.errors]
                raise ValueError(f"Validation failed: {'; '.join(err_msgs)}")

            for w in val_report.warnings:
                warnings_list.append(w.message)

        now_naive = self.clock.now().replace(tzinfo=None)

        # Check if reading already exists for this date
        existing_reading = (
            session.query(ReadingModel)
            .filter_by(customer_id=customer.id, report_date=rep_date)
            .first()
        )

        if existing_reading:
            # Snapshot old state before modifying
            old_snapshot = {
                "inverter_kwh": existing_reading.inverter_kwh,
                "eb_export_kwh": existing_reading.eb_export_kwh,
                "eb_6to10_kwh": existing_reading.eb_6to10_kwh,
                "reported_monthly_kwh": existing_reading.reported_monthly_kwh,
                "reported_yearly_kwh": existing_reading.reported_yearly_kwh,
                "inverter_availability_pct": existing_reading.inverter_availability_pct,
                "grid_availability_pct": existing_reading.grid_availability_pct,
                "fault_text": existing_reading.fault_text,
                "manual_remark": existing_reading.manual_remark,
                "auto_remark": existing_reading.auto_remark,
                "version": existing_reading.version,
            }

            revision = ReadingRevisionModel(
                reading_id=existing_reading.id,
                version=existing_reading.version,
                snapshot=json.dumps(old_snapshot),
                changed_at=now_naive,
                actor_label=reading_input.actor_label,
                reason=admin_override_reason or "Reading updated",
            )
            session.add(revision)

            existing_reading.inverter_kwh = reading_input.inverter_kwh or 0.0
            existing_reading.eb_export_kwh = reading_input.eb_export_kwh or 0.0
            existing_reading.eb_6to10_kwh = reading_input.eb_6to10_kwh or 0.0
            existing_reading.reported_monthly_kwh = reading_input.reported_monthly_kwh
            existing_reading.reported_yearly_kwh = reading_input.reported_yearly_kwh
            existing_reading.inverter_availability_pct = reading_input.inverter_availability_pct
            existing_reading.grid_availability_pct = reading_input.grid_availability_pct
            existing_reading.fault_text = reading_input.fault_text or ""
            existing_reading.plant_weather_text = reading_input.plant_weather_text or ""
            existing_reading.plant_temp_c = reading_input.plant_temp_c
            existing_reading.manual_remark = reading_input.manual_remark or ""
            existing_reading.auto_remark = reading_input.auto_remark or ""
            existing_reading.source_upload_id = reading_input.source_upload_id
            existing_reading.entry_method = reading_input.entry_method.value
            existing_reading.version += 1
            existing_reading.actor_label = reading_input.actor_label
            existing_reading.updated_at = now_naive

            record_audit_event(
                session=session,
                clock=self.clock,
                actor_label=reading_input.actor_label,
                action="UPDATE_READING",
                entity="readings",
                entity_id=str(existing_reading.id),
                before=old_snapshot,
                after={
                    "inverter_kwh": existing_reading.inverter_kwh,
                    "eb_export_kwh": existing_reading.eb_export_kwh,
                    "version": existing_reading.version,
                },
                reason=admin_override_reason or "Updated reading",
            )
            target_reading = existing_reading
        else:
            new_reading = ReadingModel(
                customer_id=customer.id,
                report_date=rep_date,
                inverter_kwh=reading_input.inverter_kwh or 0.0,
                eb_export_kwh=reading_input.eb_export_kwh or 0.0,
                eb_6to10_kwh=reading_input.eb_6to10_kwh or 0.0,
                reported_monthly_kwh=reading_input.reported_monthly_kwh,
                reported_yearly_kwh=reading_input.reported_yearly_kwh,
                inverter_availability_pct=reading_input.inverter_availability_pct,
                grid_availability_pct=reading_input.grid_availability_pct,
                fault_text=reading_input.fault_text or "",
                plant_weather_text=reading_input.plant_weather_text or "",
                plant_temp_c=reading_input.plant_temp_c,
                manual_remark=reading_input.manual_remark or "",
                auto_remark=reading_input.auto_remark or "",
                source_upload_id=reading_input.source_upload_id,
                entry_method=reading_input.entry_method.value,
                status=ReadingStatus.ACTIVE.value,
                version=1,
                actor_label=reading_input.actor_label,
                created_at=now_naive,
                updated_at=now_naive,
            )
            session.add(new_reading)
            session.flush()

            record_audit_event(
                session=session,
                clock=self.clock,
                actor_label=reading_input.actor_label,
                action="CREATE_READING",
                entity="readings",
                entity_id=str(new_reading.id),
                after={
                    "report_date": str(new_reading.report_date),
                    "inverter_kwh": new_reading.inverter_kwh,
                    "eb_export_kwh": new_reading.eb_export_kwh,
                },
                reason="Initial entry",
            )
            target_reading = new_reading

        session.flush()
        return target_reading, warnings_list

    def get_readings_for_month(
        self,
        session: Session,
        year: int,
        month: int,
    ) -> List[ReadingModel]:
        """Fetch all active readings for a given month in date order."""
        customer = self.get_target_customer(session)
        start_d = date(year, month, 1)
        # Calculate last day of month
        import calendar
        _, last_day = calendar.monthrange(year, month)
        end_d = date(year, month, last_day)

        return (
            session.query(ReadingModel)
            .filter(
                ReadingModel.customer_id == customer.id,
                ReadingModel.report_date >= start_d,
                ReadingModel.report_date <= end_d,
                ReadingModel.status == ReadingStatus.ACTIVE.value,
            )
            .order_by(ReadingModel.report_date.asc())
            .all()
        )

    def get_running_totals_for_month(
        self,
        session: Session,
        year: int,
        month: int,
    ) -> List[DailyTotals]:
        """Calculate dynamic running totals for the month."""
        readings = self.get_readings_for_month(session, year, month)
        inputs = [
            DailyReadingInput(
                report_date=r.report_date,
                inverter_kwh=r.inverter_kwh,
                eb_export_kwh=r.eb_export_kwh,
                eb_6to10_kwh=r.eb_6to10_kwh,
                manual_remark=r.manual_remark,
                auto_remark=r.auto_remark,
            )
            for r in readings
        ]
        return calculate_running_totals(inputs, remark_mode=settings.REMARK_MODE)
