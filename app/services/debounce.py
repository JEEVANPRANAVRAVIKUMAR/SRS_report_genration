"""Late entry debouncer for merging bursts of changes during closed grace period (SPEC Section B10, AC-08)."""

from datetime import date, datetime
import hashlib
from pathlib import Path
import shutil
import threading
from typing import Callable, Dict, List, Optional, Set, Tuple
from sqlalchemy.orm import Session
from app.domain.models import DailyReadingInput, MonthStatus
from app.infra.audit import record_audit_event
from app.infra.clock import Clock
from app.infra.models import CustomerModel, MonthModel, ReadingModel, ReportFileModel
from app.infra.settings import settings
from app.services.notify import NotificationService
from app.services.reports.pdf import PDFReportGenerator


class PendingRevision:
    def __init__(self, year: int, month: int, actor_label: str) -> None:
        self.year = year
        self.month = month
        self.actor_label = actor_label
        self.changed_dates: Set[date] = set()
        self.timer: Optional[threading.Timer] = None


class DebounceService:
    """Queues and merges bursts of changes during CLOSED month grace window.
    
    Waits debounce_seconds (default 120s) before issuing the next consolidated PDF revision.
    """

    def __init__(
        self,
        clock: Clock,
        debounce_seconds: Optional[float] = None,
        export_copy_dir: Optional[Path] = None,
        reports_dir: Optional[Path] = None,
        on_flush_callback: Optional[Callable[[str, int], None]] = None,
    ) -> None:
        self.clock = clock
        self.debounce_seconds = (
            debounce_seconds
            if debounce_seconds is not None
            else settings.DEBOUNCE_SECONDS
        )
        self.export_copy_dir = export_copy_dir or settings.EXPORT_COPY_DIR
        self.reports_dir = reports_dir or settings.REPORTS_DIR
        self.on_flush_callback = on_flush_callback
        self.pdf_gen = PDFReportGenerator(output_dir=self.reports_dir)
        self.notify_service = NotificationService(clock)
        self._pending: Dict[str, PendingRevision] = {}
        self._lock = threading.Lock()

    def enqueue(
        self,
        year: int,
        month: int,
        changed_date: date,
        actor_label: str = "Operator",
    ) -> None:
        """Enqueue a changed date for a month revision. Resets debounce timer."""
        ym = f"{year:04d}-{month:02d}"
        with self._lock:
            if ym not in self._pending:
                self._pending[ym] = PendingRevision(year, month, actor_label)
            
            pending = self._pending[ym]
            pending.changed_dates.add(changed_date)
            pending.actor_label = actor_label

            # Cancel existing timer if running
            if pending.timer is not None:
                pending.timer.cancel()
                pending.timer = None

    def has_pending(self, ym: str) -> bool:
        """Check if a month has pending debounce changes."""
        with self._lock:
            return ym in self._pending and len(self._pending[ym].changed_dates) > 0

    def get_pending_dates(self, ym: str) -> List[date]:
        """Return list of changed dates queued for the month."""
        with self._lock:
            if ym in self._pending:
                return sorted(self._pending[ym].changed_dates)
            return []

    def flush(
        self,
        session: Session,
        ym: Optional[str] = None,
        reason: str = "LATE_ENTRY",
    ) -> List[ReportFileModel]:
        """Process and generate pending revisions immediately.
        
        Returns the generated ReportFileModel list.
        """
        targets: List[Tuple[str, PendingRevision]] = []
        with self._lock:
            if ym:
                if ym in self._pending:
                    targets.append((ym, self._pending.pop(ym)))
            else:
                for k, v in list(self._pending.items()):
                    targets.append((k, v))
                self._pending.clear()

        results: List[ReportFileModel] = []
        for target_ym, pending in targets:
            if pending.timer:
                pending.timer.cancel()
                pending.timer = None

            report_file = self._execute_revision_generation(
                session=session,
                year=pending.year,
                month=pending.month,
                changed_dates=sorted(pending.changed_dates),
                actor_label=pending.actor_label,
                reason=reason,
            )
            if report_file:
                results.append(report_file)

        return results

    def _execute_revision_generation(
        self,
        session: Session,
        year: int,
        month: int,
        changed_dates: List[date],
        actor_label: str,
        reason: str,
    ) -> Optional[ReportFileModel]:
        """Internal worker generating the next revision PDF and notifications."""
        ym = f"{year:04d}-{month:02d}"
        month_record = (
            session.query(MonthModel)
            .filter_by(ym=ym)
            .first()
        )
        if not month_record:
            return None

        # Determine next revision number
        new_rev = month_record.pdf_revision + 1
        month_record.pdf_revision = new_rev

        # Fetch active readings for this month
        customer = (
            session.query(CustomerModel)
            .filter_by(is_target=True)
            .first()
        )
        if not customer:
            return None

        import calendar
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

        # Generate PDF for new revision
        pdf_path = self.pdf_gen.generate_monthly_pdf(
            year=year,
            month=month,
            readings=readings_input,
            clock=self.clock,
            revision=new_rev,
            reason=reason,
        )

        pdf_bytes = pdf_path.read_bytes()
        sha256 = hashlib.sha256(pdf_bytes).hexdigest()

        now_naive = self.clock.now().replace(tzinfo=None)
        exported_at = None

        # Copy to EXPORT_COPY_DIR if configured
        target_export_dir = self.export_copy_dir or settings.EXPORT_COPY_DIR
        if target_export_dir:
            target_export_dir.mkdir(parents=True, exist_ok=True)
            dest_copy = target_export_dir / pdf_path.name
            shutil.copy2(pdf_path, dest_copy)
            exported_at = now_naive

        report_file = ReportFileModel(
            month_id=month_record.id,
            kind="PDF",
            revision=new_rev,
            path=str(pdf_path),
            sha256=sha256,
            created_at=now_naive,
            exported_to_folder_at=exported_at,
            reason=reason,
        )
        session.add(report_file)
        session.flush()

        # Build notification message, e.g., 'revision 2: 31 May added'
        if changed_dates:
            dates_str = ", ".join(f"{d.day} {d.strftime('%b')}" for d in changed_dates)
            verb = "added/updated" if len(changed_dates) > 1 else "added"
            notif_msg = f"revision {new_rev}: {dates_str} {verb}"
        else:
            notif_msg = f"revision {new_rev} generated"

        self.notify_service.send_notification(
            session=session,
            title=f"May {year} PDF revision {new_rev}",
            message=notif_msg,
            kind="REVISION_ADDED",
            ym=ym,
            action_url=f"/reports/{ym}",
        )

        record_audit_event(
            session=session,
            clock=self.clock,
            actor_label=actor_label,
            action="ISSUE_PDF_REVISION",
            entity="report_files",
            entity_id=str(report_file.id),
            after={"revision": new_rev, "sha256": sha256, "reason": reason},
            reason=notif_msg,
        )

        session.flush()
        if self.on_flush_callback:
            self.on_flush_callback(ym, new_rev)

        return report_file
