"""Month lifecycle management and transitions matching docs/SPEC.md Section B10."""

import calendar
from datetime import date, datetime, timedelta
import hashlib
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo
from app.domain.models import DailyReadingInput, MonthStatus, UserRole
from app.domain.months import (
    determine_month_status,
    format_month_label,
    get_month_close_datetime,
    get_month_lock_datetime,
)
from app.infra.audit import record_audit_event
from app.infra.clock import Clock
from app.infra.models import (
    CustomerModel,
    JobRunModel,
    MonthModel,
    ReadingModel,
    ReportFileModel,
)
from app.infra.settings import settings
from app.services.debounce import DebounceService
from app.services.notify import NotificationService
from app.services.reports.excel import ExcelReportGenerator
from app.services.reports.pdf import PDFReportGenerator
from app.services.weather.client import OpenMeteoClient
from app.services.weather.service import WeatherService

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


class MonthLifecycleService:
    """Orchestrates month closure, late entries, locking, and startup catch-up."""

    def __init__(
        self,
        clock: Clock,
        weather_client: Optional[OpenMeteoClient] = None,
        export_copy_dir: Optional[Path] = None,
        debounce_seconds: Optional[float] = None,
        reports_dir: Optional[Path] = None,
        workbooks_dir: Optional[Path] = None,
    ) -> None:
        self.clock = clock
        self.export_copy_dir = export_copy_dir or settings.EXPORT_COPY_DIR
        self.reports_dir = reports_dir or settings.REPORTS_DIR
        self.workbooks_dir = workbooks_dir or settings.WORKBOOKS_DIR
        self.pdf_gen = PDFReportGenerator(output_dir=self.reports_dir)
        self.excel_gen = ExcelReportGenerator(output_dir=self.workbooks_dir)
        self.weather_service = WeatherService(clock, client=weather_client)
        self.notify_service = NotificationService(clock)
        self.debounce_service = DebounceService(
            clock=clock,
            debounce_seconds=debounce_seconds,
            export_copy_dir=self.export_copy_dir,
            reports_dir=self.reports_dir,
        )

    def _get_target_customer(self, session: Session) -> CustomerModel:
        customer = session.query(CustomerModel).filter_by(is_target=True).first()
        if not customer:
            raise ValueError("Target customer not found.")
        return customer

    def get_or_create_month_record(
        self,
        session: Session,
        customer_id: int,
        year: int,
        month: int,
    ) -> MonthModel:
        """Get or initialize MonthModel."""
        ym = f"{year:04d}-{month:02d}"
        rec = session.query(MonthModel).filter_by(customer_id=customer_id, ym=ym).first()
        if not rec:
            status = determine_month_status(
                year=year,
                month=month,
                current_time=self.clock.now(),
                close_time_str=settings.CLOSE_TIME,
                grace_days=settings.GRACE_DAYS,
            )
            rec = MonthModel(
                customer_id=customer_id,
                ym=ym,
                status=status.value,
                pdf_revision=1,
            )
            session.add(rec)
            session.flush()
        return rec

    def close_month(
        self,
        session: Session,
        year: int,
        month: int,
        is_late_close: bool = False,
        actor_label: str = "System",
        reason: str = "",
    ) -> Tuple[bool, str]:
        """Idempotently close the given month.
        
        1. Checks job_runs & month status to guarantee idempotency.
        2. Refreshes provisional weather.
        3. Generates PDF revision 1 and stores hash.
        4. Rebuilds the Excel workbook.
        5. Copies PDF to EXPORT_COPY_DIR if set.
        6. Creates the new month's sheet / record.
        7. Sends in-app notification badge.
        8. Records audit event and updates job_runs.
        """
        ym = f"{year:04d}-{month:02d}"
        customer = self._get_target_customer(session)
        now_dt = self.clock.now()
        now_naive = now_dt.replace(tzinfo=None)

        # 1. Idempotency check via job_runs
        existing_job = (
            session.query(JobRunModel)
            .filter_by(job_name="MONTH_CLOSE", period=ym)
            .first()
        )
        if existing_job and existing_job.status == "SUCCESS":
            return False, f"Month {ym} was already closed on {existing_job.finished_at}."

        month_record = self.get_or_create_month_record(session, customer.id, year, month)
        if month_record.status in [MonthStatus.CLOSED.value, MonthStatus.LOCKED.value]:
            existing_pdf = (
                session.query(ReportFileModel)
                .filter_by(month_id=month_record.id, kind="PDF", revision=1)
                .first()
            )
            if existing_pdf and existing_job and existing_job.status == "SUCCESS":
                return False, f"Month {ym} is already closed."

        # Mark job run started
        if not existing_job:
            job_run = JobRunModel(
                job_name="MONTH_CLOSE",
                period=ym,
                started_at=now_naive,
                status="RUNNING",
            )
            session.add(job_run)
            session.flush()
        else:
            job_run = existing_job
            job_run.started_at = now_naive
            job_run.status = "RUNNING"
            session.flush()

        # Update Month state
        month_record.status = MonthStatus.CLOSED.value
        month_record.closed_at = now_naive

        # Ensure the next month's record exists (B10: 'create the new month's sheet')
        if month == 12:
            next_year = year + 1
            next_month = 1
        else:
            next_year = year
            next_month = month + 1
        next_month_record = self.get_or_create_month_record(session, customer.id, next_year, next_month)

        # 2. Refresh provisional weather for the closed month
        try:
            self.weather_service.refresh_provisional_readings(session, plant_id=1)
        except Exception:
            pass  # Resilient to external weather service outages during close

        # Fetch active readings for this month
        _, last_day = calendar.monthrange(year, month)
        db_readings = (
            session.query(ReadingModel)
            .filter(
                ReadingModel.customer_id == customer.id,
                ReadingModel.report_date >= date(year, month, 1),
                ReadingModel.report_date <= date(year, month, last_day),
                ReadingModel.status == "ACTIVE",
            )
            .order_by(ReadingModel.report_date.asc())
            .all()
        )

        readings_input = [
            DailyReadingInput(
                report_date=r.report_date,
                inverter_kwh=r.inverter_kwh,
                eb_export_kwh=r.eb_export_kwh,
                eb_6to10_kwh=r.eb_6to10_kwh,
                manual_remark=r.manual_remark,
                auto_remark=r.auto_remark,
            )
            for r in db_readings
        ]

        # 3. Generate PDF revision 1
        pdf_path = self.pdf_gen.generate_monthly_pdf(
            year=year,
            month=month,
            readings=readings_input,
            clock=self.clock,
            revision=1,
            reason="CLOSE",
        )
        sha256 = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

        # 4. Copy to EXPORT_COPY_DIR if configured
        exported_at = None
        target_export_dir = self.export_copy_dir or settings.EXPORT_COPY_DIR
        if target_export_dir:
            target_export_dir.mkdir(parents=True, exist_ok=True)
            dest_copy = target_export_dir / pdf_path.name
            shutil.copy2(pdf_path, dest_copy)
            exported_at = now_naive

        # Store in report_files
        existing_report = (
            session.query(ReportFileModel)
            .filter_by(month_id=month_record.id, kind="PDF", revision=1)
            .first()
        )
        if not existing_report:
            report_file = ReportFileModel(
                month_id=month_record.id,
                kind="PDF",
                revision=1,
                path=str(pdf_path),
                sha256=sha256,
                created_at=now_naive,
                exported_to_folder_at=exported_at,
                reason="CLOSE",
            )
            session.add(report_file)
        else:
            existing_report.path = str(pdf_path)
            existing_report.sha256 = sha256
            existing_report.exported_to_folder_at = exported_at

        # 5. Rebuild Excel workbook atomically
        wb_path = self.rebuild_workbook(session, year)
        month_record.workbook_path = str(wb_path)

        # 6. In-app notification: 'May 2026 PDF ready'
        month_label = format_month_label(year, month)
        self.notify_service.send_notification(
            session=session,
            title=f"{month_label} PDF ready",
            message=f"{month_label} closed. PDF revision 1 ready for download.",
            kind="PDF_READY",
            ym=ym,
            action_url=f"/reports/{ym}",
        )

        # 7. Audit log & update job_runs
        audit_action = "LATE_CLOSE" if is_late_close else "CLOSE_MONTH"
        audit_reason = "late close" if is_late_close else (reason or "Scheduled month close")
        record_audit_event(
            session=session,
            clock=self.clock,
            actor_label=actor_label,
            action=audit_action,
            entity="months",
            entity_id=ym,
            after={"status": MonthStatus.CLOSED.value, "pdf_revision": 1, "sha256": sha256},
            reason=audit_reason,
        )

        job_run.status = "SUCCESS"
        job_run.finished_at = now_naive
        job_run.message = "late close" if is_late_close else "Closed on schedule"

        session.flush()
        return True, f"Month {ym} closed successfully."

    def lock_month(
        self,
        session: Session,
        year: int,
        month: int,
        actor_label: str = "System",
    ) -> Tuple[bool, str]:
        """Transition CLOSED month to LOCKED once grace days have elapsed."""
        ym = f"{year:04d}-{month:02d}"
        customer = self._get_target_customer(session)
        month_record = self.get_or_create_month_record(session, customer.id, year, month)

        if month_record.status == MonthStatus.LOCKED.value:
            return False, f"Month {ym} is already LOCKED."

        now_naive = self.clock.now().replace(tzinfo=None)
        old_status = month_record.status
        month_record.status = MonthStatus.LOCKED.value
        month_record.locked_at = now_naive

        record_audit_event(
            session=session,
            clock=self.clock,
            actor_label=actor_label,
            action="LOCK_MONTH",
            entity="months",
            entity_id=ym,
            before={"status": old_status},
            after={"status": MonthStatus.LOCKED.value},
            reason="Grace period expired. Month locked.",
        )

        session.flush()
        return True, f"Month {ym} locked."

    def check_and_run_due_transitions(self, session: Session) -> Dict[str, Any]:
        """Safety job / start-up catch-up checking all due month closures and lockouts."""
        now_dt = self.clock.now()
        if now_dt.tzinfo is None:
            now_kolkata = now_dt.replace(tzinfo=KOLKATA_TZ)
        else:
            now_kolkata = now_dt.astimezone(KOLKATA_TZ)

        customer = self._get_target_customer(session)
        closed_months: List[str] = []
        locked_months: List[str] = []

        # Find all months in database plus candidate current/past months
        db_months = session.query(MonthModel).filter_by(customer_id=customer.id).all()
        month_map = {m.ym: m for m in db_months}

        # Check existing months and months up to current year/month
        cur_year = now_kolkata.year
        cur_month = now_kolkata.month

        # Inspect candidate months
        candidate_yms = set(month_map.keys())
        for m in range(1, cur_month + 1):
            candidate_yms.add(f"{cur_year:04d}-{m:02d}")
        # Include previous year's Dec if in Jan
        if cur_month == 1:
            candidate_yms.add(f"{cur_year - 1:04d}-12")

        for ym in sorted(candidate_yms):
            y_str, m_str = ym.split("-")
            y, m = int(y_str), int(m_str)
            month_rec = month_map.get(ym)

            close_dt = get_month_close_datetime(y, m, close_time_str=settings.CLOSE_TIME)
            lock_dt = get_month_lock_datetime(y, m, grace_days=settings.GRACE_DAYS)

            # Check if close is due
            if now_kolkata >= close_dt:
                current_status = month_rec.status if month_rec else MonthStatus.OPEN.value
                if current_status == MonthStatus.OPEN.value:
                    # If current time is significantly past close time (e.g. >1 hour), mark as late close
                    is_late = (now_kolkata > close_dt + timedelta(hours=1))
                    succ, msg = self.close_month(
                        session=session,
                        year=y,
                        month=m,
                        is_late_close=is_late,
                        actor_label="System",
                        reason="late close" if is_late else "Scheduled close",
                    )
                    if succ:
                        closed_months.append(ym)

                # Check if lock is due
                month_rec = session.query(MonthModel).filter_by(customer_id=customer.id, ym=ym).first()
                if month_rec and month_rec.status == MonthStatus.CLOSED.value:
                    if now_kolkata > lock_dt:
                        succ, msg = self.lock_month(session=session, year=y, month=m, actor_label="System")
                        if succ:
                            locked_months.append(ym)

        return {
            "closed": closed_months,
            "locked": locked_months,
            "checked_at": str(now_kolkata),
        }

    def admin_close_now(
        self,
        session: Session,
        year: int,
        month: int,
        actor_label: str = "Admin",
        reason: str = "",
    ) -> Tuple[bool, str]:
        """Admin control: close month immediately on demand."""
        return self.close_month(
            session=session,
            year=year,
            month=month,
            is_late_close=False,
            actor_label=actor_label,
            reason=reason or "Admin manual close",
        )

    def admin_reopen_month(
        self,
        session: Session,
        year: int,
        month: int,
        actor_label: str = "Admin",
        reason: str = "",
    ) -> Tuple[bool, str]:
        """Admin control: reopen a CLOSED or LOCKED month (requires written reason)."""
        if not reason or not reason.strip():
            raise ValueError("Reopening a month requires a written reason.")

        ym = f"{year:04d}-{month:02d}"
        customer = self._get_target_customer(session)
        month_rec = self.get_or_create_month_record(session, customer.id, year, month)

        old_status = month_rec.status
        month_rec.status = MonthStatus.OPEN.value

        record_audit_event(
            session=session,
            clock=self.clock,
            actor_label=actor_label,
            action="REOPEN_MONTH",
            entity="months",
            entity_id=ym,
            before={"status": old_status},
            after={"status": MonthStatus.OPEN.value},
            reason=reason,
        )

        session.flush()
        return True, f"Month {ym} reopened by {actor_label}."

    def admin_regenerate_pdf(
        self,
        session: Session,
        year: int,
        month: int,
        actor_label: str = "Admin",
        reason: str = "",
    ) -> ReportFileModel:
        """Admin control: regenerate the latest official PDF revision."""
        ym = f"{year:04d}-{month:02d}"
        customer = self._get_target_customer(session)
        month_rec = self.get_or_create_month_record(session, customer.id, year, month)

        _, last_day = calendar.monthrange(year, month)
        db_readings = (
            session.query(ReadingModel)
            .filter(
                ReadingModel.customer_id == customer.id,
                ReadingModel.report_date >= date(year, month, 1),
                ReadingModel.report_date <= date(year, month, last_day),
                ReadingModel.status == "ACTIVE",
            )
            .order_by(ReadingModel.report_date.asc())
            .all()
        )

        readings_input = [
            DailyReadingInput(
                report_date=r.report_date,
                inverter_kwh=r.inverter_kwh,
                eb_export_kwh=r.eb_export_kwh,
                eb_6to10_kwh=r.eb_6to10_kwh,
                manual_remark=r.manual_remark,
                auto_remark=r.auto_remark,
            )
            for r in db_readings
        ]

        pdf_path = self.pdf_gen.generate_monthly_pdf(
            year=year,
            month=month,
            readings=readings_input,
            clock=self.clock,
            revision=month_rec.pdf_revision,
            reason=reason or "ADMIN_REGENERATE",
        )
        sha256 = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

        now_naive = self.clock.now().replace(tzinfo=None)
        rep = (
            session.query(ReportFileModel)
            .filter_by(month_id=month_rec.id, kind="PDF", revision=month_rec.pdf_revision)
            .first()
        )
        if rep:
            rep.path = str(pdf_path)
            rep.sha256 = sha256
            rep.created_at = now_naive
        else:
            rep = ReportFileModel(
                month_id=month_rec.id,
                kind="PDF",
                revision=month_rec.pdf_revision,
                path=str(pdf_path),
                sha256=sha256,
                created_at=now_naive,
                reason="ADMIN_REGENERATE",
            )
            session.add(rep)

        record_audit_event(
            session=session,
            clock=self.clock,
            actor_label=actor_label,
            action="REGENERATE_PDF",
            entity="report_files",
            entity_id=str(rep.id),
            after={"revision": month_rec.pdf_revision, "sha256": sha256},
            reason=reason or "Admin requested PDF regeneration",
        )

        session.flush()
        return rep

    def handle_reading_saved(
        self,
        session: Session,
        reading_date: date,
        role: UserRole = UserRole.OPERATOR,
        actor_label: str = "Operator",
        admin_reason: str = "",
    ) -> Optional[ReportFileModel]:
        """Post-commit handler for newly saved/updated readings.
        
        1. Always rebuilds Excel workbook.
        2. If month is CLOSED: queues debounce revision.
        3. If month is LOCKED: generates 'post-lock amendment' PDF revision immediately.
        """
        year, month = reading_date.year, reading_date.month
        customer = self._get_target_customer(session)
        month_rec = self.get_or_create_month_record(session, customer.id, year, month)

        # 1. Rebuild workbook
        self.rebuild_workbook(session, year)

        # 2. Check month status
        if month_rec.status == MonthStatus.CLOSED.value:
            # Late entry within grace period -> debounce
            self.debounce_service.enqueue(year, month, reading_date, actor_label)
            # If debouncer configured with 0 delay, flush immediately
            if self.debounce_service.debounce_seconds <= 0:
                reps = self.debounce_service.flush(session, ym=month_rec.ym)
                return reps[0] if reps else None
            return None

        elif month_rec.status == MonthStatus.LOCKED.value:
            # Admin post-lock amendment -> immediate next revision marked 'post-lock amendment'
            new_rev = month_rec.pdf_revision + 1
            month_rec.pdf_revision = new_rev

            _, last_day = calendar.monthrange(year, month)
            db_readings = (
                session.query(ReadingModel)
                .filter(
                    ReadingModel.customer_id == customer.id,
                    ReadingModel.report_date >= date(year, month, 1),
                    ReadingModel.report_date <= date(year, month, last_day),
                    ReadingModel.status == "ACTIVE",
                )
                .order_by(ReadingModel.report_date.asc())
                .all()
            )

            readings_input = [
                DailyReadingInput(
                    report_date=r.report_date,
                    inverter_kwh=r.inverter_kwh,
                    eb_export_kwh=r.eb_export_kwh,
                    eb_6to10_kwh=r.eb_6to10_kwh,
                    manual_remark=r.manual_remark,
                    auto_remark=r.auto_remark,
                )
                for r in db_readings
            ]

            pdf_path = self.pdf_gen.generate_monthly_pdf(
                year=year,
                month=month,
                readings=readings_input,
                clock=self.clock,
                revision=new_rev,
                reason="post-lock amendment",
            )
            sha256 = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
            now_naive = self.clock.now().replace(tzinfo=None)

            exported_at = None
            target_export_dir = self.export_copy_dir or settings.EXPORT_COPY_DIR
            if target_export_dir:
                target_export_dir.mkdir(parents=True, exist_ok=True)
                dest_copy = target_export_dir / pdf_path.name
                shutil.copy2(pdf_path, dest_copy)
                exported_at = now_naive

            report_file = ReportFileModel(
                month_id=month_rec.id,
                kind="PDF",
                revision=new_rev,
                path=str(pdf_path),
                sha256=sha256,
                created_at=now_naive,
                exported_to_folder_at=exported_at,
                reason="POST_LOCK_AMENDMENT",
            )
            session.add(report_file)
            session.flush()

            self.notify_service.send_notification(
                session=session,
                title=f"{format_month_label(year, month)} Post-Lock Amendment",
                message=f"revision {new_rev}: post-lock amendment ({admin_reason})",
                kind="REVISION_ADDED",
                ym=month_rec.ym,
                action_url=f"/reports/{month_rec.ym}",
            )

            record_audit_event(
                session=session,
                clock=self.clock,
                actor_label=actor_label,
                action="POST_LOCK_AMENDMENT",
                entity="report_files",
                entity_id=str(report_file.id),
                after={"revision": new_rev, "sha256": sha256},
                reason=admin_reason,
            )

            session.flush()
            return report_file

        return None

    def rebuild_workbook(self, session: Session, year: int) -> Path:
        """Rebuild annual Excel workbook from the database."""
        customer = self._get_target_customer(session)

        # Query all active readings for this year
        db_readings = (
            session.query(ReadingModel)
            .filter(
                ReadingModel.customer_id == customer.id,
                ReadingModel.report_date >= date(year, 1, 1),
                ReadingModel.report_date <= date(year, 12, 31),
                ReadingModel.status == "ACTIVE",
            )
            .order_by(ReadingModel.report_date.asc())
            .all()
        )

        readings_by_month: Dict[int, List[DailyReadingInput]] = {}
        for r in db_readings:
            m = r.report_date.month
            if m not in readings_by_month:
                readings_by_month[m] = []
            readings_by_month[m].append(
                DailyReadingInput(
                    report_date=r.report_date,
                    inverter_kwh=r.inverter_kwh,
                    eb_export_kwh=r.eb_export_kwh,
                    eb_6to10_kwh=r.eb_6to10_kwh,
                    manual_remark=r.manual_remark,
                    auto_remark=r.auto_remark,
                )
            )

        # Query month records to pass statuses and revisions
        month_records = (
            session.query(MonthModel)
            .filter(
                MonthModel.customer_id == customer.id,
                MonthModel.ym.like(f"{year:04d}-%"),
            )
            .all()
        )
        month_statuses: Dict[int, MonthStatus] = {}
        month_revisions: Dict[int, int] = {}
        for rec in month_records:
            m = int(rec.ym.split("-")[1])
            month_statuses[m] = MonthStatus(rec.status)
            month_revisions[m] = rec.pdf_revision

        return self.excel_gen.generate_annual_workbook(
            year=year,
            readings_by_month=readings_by_month,
            month_statuses=month_statuses,
            month_revisions=month_revisions,
        )
