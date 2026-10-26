"""Security, CSRF protection, and Role-Based Access Control (RBAC) matching SPEC Section B13 and AC-20."""

from datetime import datetime, timedelta
import hmac
import os
import secrets
from typing import Any, Dict, Optional, Set, Tuple
from app.domain.models import UserRole
from app.infra.clock import Clock, SystemClock
from app.infra.settings import settings


class SessionData:
    def __init__(
        self,
        session_id: str,
        user_id: int,
        username: str,
        role: UserRole,
        actor_label: str,
        csrf_token: str,
        created_at: datetime,
        last_active_at: datetime,
    ) -> None:
        self.session_id = session_id
        self.user_id = user_id
        self.username = username
        self.role = role
        self.actor_label = actor_label
        self.csrf_token = csrf_token
        self.created_at = created_at
        self.last_active_at = last_active_at


class SecurityManager:
    """Manages sessions, CSRF token validation, role-based authorization, and rate limiting."""

    ADMIN_IDLE_TIMEOUT = timedelta(minutes=30)
    OPERATOR_IDLE_TIMEOUT = timedelta(hours=12)

    def __init__(self, clock: Optional[Clock] = None) -> None:
        self.clock = clock or SystemClock()
        self._sessions: Dict[str, SessionData] = {}
        self._login_attempts: Dict[str, Tuple[int, Optional[datetime]]] = {}

    def generate_csrf_token(self) -> str:
        """Generate a cryptographically secure 256-bit CSRF token."""
        return secrets.token_hex(32)

    def create_session(
        self,
        user_id: int,
        username: str,
        role: UserRole,
        actor_label: str,
    ) -> SessionData:
        """Initialize an authenticated session with a fresh CSRF token."""
        now_dt = self.clock.now()
        session_id = secrets.token_urlsafe(32)
        csrf_token = self.generate_csrf_token()

        sess = SessionData(
            session_id=session_id,
            user_id=user_id,
            username=username,
            role=role,
            actor_label=actor_label,
            csrf_token=csrf_token,
            created_at=now_dt,
            last_active_at=now_dt,
        )
        self._sessions[session_id] = sess
        return sess

    def get_session(self, session_id: Optional[str]) -> Optional[SessionData]:
        """Validate and return active session, enforcing idle session expiration."""
        if not session_id or session_id not in self._sessions:
            return None

        sess = self._sessions[session_id]
        now_dt = self.clock.now()

        # Check session expiry (Admin: 30 minutes idle; Operator: 12 hours)
        timeout = self.ADMIN_IDLE_TIMEOUT if sess.role == UserRole.ADMIN else self.OPERATOR_IDLE_TIMEOUT
        if now_dt - sess.last_active_at > timeout:
            self.terminate_session(session_id)
            return None

        sess.last_active_at = now_dt
        return sess

    def terminate_session(self, session_id: str) -> None:
        """Remove session on logout or expiry."""
        self._sessions.pop(session_id, None)

    def validate_csrf(
        self,
        session: Optional[SessionData],
        submitted_token: Optional[str],
    ) -> bool:
        """Validate state-changing request CSRF token using constant-time comparison."""
        if not session or not submitted_token:
            return False
        return hmac.compare_digest(session.csrf_token, submitted_token.strip())

    def check_rate_limit_and_lockout(self, username: str) -> Tuple[bool, int]:
        """Check failed login attempts and calculate lockout remaining seconds.
        
        Rule (B2 & B13): After 5 failed tries, wait 15 minutes, doubling each subsequent failure.
        Returns (is_locked, remaining_seconds).
        """
        now_dt = self.clock.now()
        attempts, locked_until = self._login_attempts.get(username, (0, None))

        if locked_until and now_dt < locked_until:
            remaining = int((locked_until - now_dt).total_seconds())
            return True, max(remaining, 1)

        return False, 0

    def record_login_attempt(self, username: str, success: bool) -> None:
        """Record login outcome; handle exponential lockout calculation."""
        now_dt = self.clock.now()
        if success:
            self._login_attempts.pop(username, None)
            return

        attempts, _ = self._login_attempts.get(username, (0, None))
        attempts += 1

        locked_until = None
        if attempts >= 5:
            multiplier = 2 ** (attempts - 5)
            lockout_mins = 15 * multiplier
            locked_until = now_dt + timedelta(minutes=lockout_mins)

        self._login_attempts[username] = (attempts, locked_until)

    def authorize_route(
        self,
        session: Optional[SessionData],
        required_role: Optional[UserRole] = None,
        method: str = "GET",
        csrf_token: Optional[str] = None,
    ) -> Tuple[bool, int, str]:
        """Enforce CSRF and Role-Based Access Control matrix.
        
        Returns (authorized, status_code, error_message).
        """
        method = method.upper()

        # 1. State-changing requests without a valid CSRF token must fail (AC-20)
        if method in ["POST", "PUT", "PATCH", "DELETE"]:
            if not self.validate_csrf(session, csrf_token):
                return False, 403, "CSRF token missing or invalid."

        # 2. Public routes (required_role is None)
        if required_role is None:
            return True, 200, ""

        # 3. Protected route requires active session
        if not session:
            return False, 401, "Authentication required."

        # 4. Role Hierarchy: ADMIN has access to everything; OPERATOR restricted
        if required_role == UserRole.ADMIN and session.role != UserRole.ADMIN:
            return False, 403, "Forbidden: Administrative privilege required."

        return True, 200, ""
