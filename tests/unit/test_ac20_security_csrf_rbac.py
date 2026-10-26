"""Unit tests for Acceptance Criteria AC-20:
Every route enforces the role matrix; state-changing requests without a CSRF token fail.
"""

from datetime import datetime, timedelta
import unittest
from app.domain.models import UserRole
from app.infra.clock import FakeClock
from app.web.security import SecurityManager


class TestAC20SecurityCSRFRBAC(unittest.TestCase):
    def setUp(self) -> None:
        self.start_dt = datetime(2026, 6, 1, 10, 0, 0)
        self.clock = FakeClock(self.start_dt)
        self.sec = SecurityManager(clock=self.clock)

        # Setup sessions
        self.operator_session = self.sec.create_session(
            user_id=1,
            username="operator1",
            role=UserRole.OPERATOR,
            actor_label="Operator",
        )

        self.admin_session = self.sec.create_session(
            user_id=2,
            username="admin1",
            role=UserRole.ADMIN,
            actor_label="Admin",
        )

    def test_csrf_protection_on_state_changing_methods(self) -> None:
        """AC-20: State-changing requests (POST, PATCH, PUT, DELETE) without CSRF token fail with 403."""
        # 1. POST without CSRF token
        auth, code, msg = self.sec.authorize_route(
            session=self.operator_session,
            required_role=UserRole.OPERATOR,
            method="POST",
            csrf_token=None,
        )
        self.assertFalse(auth)
        self.assertEqual(code, 403)
        self.assertIn("CSRF", msg)

        # 2. PATCH with invalid CSRF token
        auth, code, msg = self.sec.authorize_route(
            session=self.operator_session,
            required_role=UserRole.OPERATOR,
            method="PATCH",
            csrf_token="invalid_tampered_token",
        )
        self.assertFalse(auth)
        self.assertEqual(code, 403)

        # 3. POST with correct CSRF token succeeds
        auth, code, msg = self.sec.authorize_route(
            session=self.operator_session,
            required_role=UserRole.OPERATOR,
            method="POST",
            csrf_token=self.operator_session.csrf_token,
        )
        self.assertTrue(auth)
        self.assertEqual(code, 200)

        # 4. Safe method (GET) does not require CSRF token
        auth, code, msg = self.sec.authorize_route(
            session=self.operator_session,
            required_role=UserRole.OPERATOR,
            method="GET",
            csrf_token=None,
        )
        self.assertTrue(auth)
        self.assertEqual(code, 200)

    def test_role_based_access_control_matrix(self) -> None:
        """AC-20: Role matrix enforcement across unauthenticated, operator, and admin users."""
        # 1. Unauthenticated request to protected route
        auth, code, msg = self.sec.authorize_route(
            session=None,
            required_role=UserRole.OPERATOR,
            method="GET",
        )
        self.assertFalse(auth)
        self.assertEqual(code, 401)

        # 2. Operator accessing Operator route -> ALLOWED
        auth, code, msg = self.sec.authorize_route(
            session=self.operator_session,
            required_role=UserRole.OPERATOR,
            method="GET",
        )
        self.assertTrue(auth)
        self.assertEqual(code, 200)

        # 3. Operator attempting Admin-only route -> FORBIDDEN (403)
        auth, code, msg = self.sec.authorize_route(
            session=self.operator_session,
            required_role=UserRole.ADMIN,
            method="POST",
            csrf_token=self.operator_session.csrf_token,
        )
        self.assertFalse(auth)
        self.assertEqual(code, 403)
        self.assertIn("Administrative privilege required", msg)

        # 4. Admin accessing Admin-only route -> ALLOWED (200)
        auth, code, msg = self.sec.authorize_route(
            session=self.admin_session,
            required_role=UserRole.ADMIN,
            method="POST",
            csrf_token=self.admin_session.csrf_token,
        )
        self.assertTrue(auth)
        self.assertEqual(code, 200)

        # 5. Admin accessing Operator route -> ALLOWED (200)
        auth, code, msg = self.sec.authorize_route(
            session=self.admin_session,
            required_role=UserRole.OPERATOR,
            method="GET",
        )
        self.assertTrue(auth)
        self.assertEqual(code, 200)

    def test_admin_session_idle_expiration(self) -> None:
        """B13: Admin session expires after 30 minutes of inactivity."""
        sess_id = self.admin_session.session_id

        # At 25 minutes, session is still valid
        self.clock.advance(minutes=25)
        sess = self.sec.get_session(sess_id)
        self.assertIsNotNone(sess)

        # Advance another 35 minutes (total 60 mins from start, >30 mins idle)
        self.clock.advance(minutes=35)
        expired_sess = self.sec.get_session(sess_id)
        self.assertIsNone(expired_sess, "Admin session must expire after 30 minutes idle!")

    def test_brute_force_exponential_lockout(self) -> None:
        """B2 & B13: 5 failed attempts locks out for 15 minutes, doubling each time."""
        username = "admin"

        # First 4 failed attempts: not locked out
        for _ in range(4):
            self.sec.record_login_attempt(username, success=False)
            locked, secs = self.sec.check_rate_limit_and_lockout(username)
            self.assertFalse(locked)

        # 5th failed attempt: triggers 15 minute lockout
        self.sec.record_login_attempt(username, success=False)
        locked, secs = self.sec.check_rate_limit_and_lockout(username)
        self.assertTrue(locked)
        self.assertGreater(secs, 800)  # ~900s = 15 mins

        # Advance 16 minutes: lockout expires
        self.clock.advance(minutes=16)
        locked_after, _ = self.sec.check_rate_limit_and_lockout(username)
        self.assertFalse(locked_after)

        # 6th failed attempt: doubles lockout to 30 minutes
        self.sec.record_login_attempt(username, success=False)
        locked, secs = self.sec.check_rate_limit_and_lockout(username)
        self.assertTrue(locked)
        self.assertGreater(secs, 1700)  # ~1800s = 30 mins


if __name__ == "__main__":
    unittest.main()
