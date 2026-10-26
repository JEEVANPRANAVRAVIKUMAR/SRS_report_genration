"""Background scheduler and start-up catch-up matching docs/SPEC.md Section B10."""

from datetime import datetime
import logging
from typing import Callable, Optional
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session
from app.infra.clock import Clock, SystemClock
from app.infra.db import get_session
from app.services.month_lifecycle import MonthLifecycleService

logger = logging.getLogger(__name__)
KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


class SolarScheduler:
    """Manages APScheduler background jobs for monthly closing, safety intervals, and startup catch-up."""

    def __init__(
        self,
        clock: Optional[Clock] = None,
        session_factory: Callable[[], Session] = get_session,
        lifecycle_service: Optional[MonthLifecycleService] = None,
    ) -> None:
        self.clock = clock or SystemClock()
        self.session_factory = session_factory
        self.lifecycle_service = lifecycle_service or MonthLifecycleService(clock=self.clock)
        self.scheduler = BackgroundScheduler(timezone=KOLKATA_TZ)
        self._is_running = False

    def setup_jobs(self) -> None:
        """Register the cron trigger and the 15-minute safety check trigger."""
        # 00:05 IST on the 1st of every month
        self.scheduler.add_job(
            func=self._execute_transitions_job,
            trigger=CronTrigger(day=1, hour=0, minute=5, timezone=KOLKATA_TZ),
            id="monthly_close_cron",
            name="Monthly Close at 00:05 IST on 1st",
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=3600,
            max_instances=1,
        )

        # Safety job every 15 minutes
        self.scheduler.add_job(
            func=self._execute_transitions_job,
            trigger=IntervalTrigger(minutes=15),
            id="safety_check_15m",
            name="Safety check every 15 minutes",
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=300,
            max_instances=1,
        )

    def _execute_transitions_job(self) -> None:
        """Internal callback to run due lifecycle transitions in an isolated session."""
        session = self.session_factory()
        try:
            results = self.lifecycle_service.check_and_run_due_transitions(session)
            session.commit()
            if results.get("closed") or results.get("locked"):
                logger.info(f"SolarScheduler executed transitions: {results}")
        except Exception as e:
            session.rollback()
            logger.error(f"Error during scheduled lifecycle execution: {e}", exc_info=True)
        finally:
            session.close()

    def run_catchup_at_startup(self) -> dict:
        """Startup catch-up check: executes immediately when application starts."""
        session = self.session_factory()
        try:
            results = self.lifecycle_service.check_and_run_due_transitions(session)
            session.commit()
            return results
        except Exception as e:
            session.rollback()
            logger.error(f"Error during startup catch-up: {e}", exc_info=True)
            raise
        finally:
            session.close()

    def start(self, run_startup_catchup: bool = True) -> None:
        """Start the background scheduler, running startup catch-up first."""
        if run_startup_catchup:
            self.run_catchup_at_startup()

        if not self._is_running:
            self.setup_jobs()
            self.scheduler.start()
            self._is_running = True

    def shutdown(self, wait: bool = False) -> None:
        """Gracefully shutdown background scheduler."""
        if self._is_running:
            self.scheduler.shutdown(wait=wait)
            self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running
