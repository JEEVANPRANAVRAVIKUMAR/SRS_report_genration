"""Unit tests for Injected Clock, Audit Logging, and User Lockout."""

from datetime import datetime, timedelta
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.domain.models import MonthStatus, UserRole
from app.domain.months import determine_month_status
from app.infra.audit import record_audit_event
from app.infra.clock import FakeClock, KOLKATA_TZ
from app.infra.db import init_db
from app.infra.models import AuditLogModel, Base
from app.services.user_service import UserService


class TestClockAndAudit(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        init_db(engine_override=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.clock = FakeClock(datetime(2026, 5, 22, 12, 0, 0, tzinfo=KOLKATA_TZ))

    def test_clock_timezone_and_advance(self) -> None:
        self.assertEqual(self.clock.timezone, KOLKATA_TZ)
        t1 = self.clock.now()
        self.clock.advance(timedelta(hours=2))
        t2 = self.clock.now()
        self.assertEqual((t2 - t1).total_seconds(), 7200)

    def test_month_status_lifecycle(self) -> None:
        # May 2026: closes on 2026-06-01 00:05 IST
        # 31 May 23:59 IST -> OPEN
        t_open = datetime(2026, 5, 31, 23, 59, 0, tzinfo=KOLKATA_TZ)
        self.assertEqual(determine_month_status(2026, 5, t_open), MonthStatus.OPEN)

        # 1 June 00:06 IST -> CLOSED
        t_closed = datetime(2026, 6, 1, 0, 6, 0, tzinfo=KOLKATA_TZ)
        self.assertEqual(determine_month_status(2026, 5, t_closed), MonthStatus.CLOSED)

        # 3 June 23:50 IST (grace period day 3) -> CLOSED
        t_grace = datetime(2026, 6, 3, 23, 50, 0, tzinfo=KOLKATA_TZ)
        self.assertEqual(determine_month_status(2026, 5, t_grace), MonthStatus.CLOSED)

        # 4 June 00:01 IST -> LOCKED
        t_locked = datetime(2026, 6, 4, 0, 1, 0, tzinfo=KOLKATA_TZ)
        self.assertEqual(determine_month_status(2026, 5, t_locked), MonthStatus.LOCKED)

    def test_user_lockout_after_5_failed_attempts(self) -> None:
        user_service = UserService(self.clock)
        with self.Session() as session:
            user = user_service.create_user(
                session=session,
                username="operator_test",
                secret="secret123",
                role=UserRole.OPERATOR,
                actor_label="Test Op",
            )
            session.commit()

            # 4 failed attempts: not locked out yet
            for i in range(4):
                u, err = user_service.authenticate(session, "operator_test", "wrong")
                self.assertIsNone(u)
                self.assertIn("attempt(s) remaining", err)

            # 5th failed attempt: triggers 15 minute lockout
            u, err = user_service.authenticate(session, "operator_test", "wrong")
            self.assertIsNone(u)
            self.assertIn("locked for 15 minutes", err)

            # Further attempts while locked out are immediately rejected
            u, err = user_service.authenticate(session, "operator_test", "secret123")
            self.assertIsNone(u)
            self.assertIn("Account is locked", err)

            # Advance clock by 16 minutes: lockout expired
            self.clock.advance(timedelta(minutes=16))
            u, err = user_service.authenticate(session, "operator_test", "secret123")
            self.assertIsNotNone(u)
            self.assertIsNone(err)

    def test_audit_log_recording(self) -> None:
        with self.Session() as session:
            record_audit_event(
                session=session,
                clock=self.clock,
                actor_label="Admin",
                action="MANUAL_EDIT",
                entity="readings",
                entity_id="123",
                before={"inverter": 6000},
                after={"inverter": 6500},
                reason="Meter reading typo correction",
            )
            session.commit()

            entry = session.query(AuditLogModel).filter_by(entity_id="123").first()
            self.assertIsNotNone(entry)
            self.assertEqual(entry.action, "MANUAL_EDIT")
            self.assertEqual(entry.reason, "Meter reading typo correction")
            self.assertIn("6000", entry.before)
            self.assertIn("6500", entry.after)


if __name__ == "__main__":
    unittest.main()
