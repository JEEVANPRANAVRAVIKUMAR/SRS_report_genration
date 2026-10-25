"""User management and authentication service with lockout enforcement."""

from datetime import timedelta
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from app.domain.models import UserRole
from app.infra.audit import record_audit_event
from app.infra.clock import Clock
from app.infra.models import UserModel
from app.infra.security import (
    check_user_lockout,
    compute_lockout_duration_minutes,
    hash_pin_or_password,
    verify_pin_or_password,
)


class UserService:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock

    def create_user(
        self,
        session: Session,
        username: str,
        secret: str,
        role: UserRole = UserRole.OPERATOR,
        actor_label: Optional[str] = None,
        creator_actor: str = "System",
    ) -> UserModel:
        """Create a new user with hashed PIN/password."""
        existing = session.query(UserModel).filter_by(username=username).first()
        if existing:
            raise ValueError(f"User '{username}' already exists")

        pw_hash, salt = hash_pin_or_password(secret)
        label = actor_label or ("Admin" if role == UserRole.ADMIN else "Operator")

        user = UserModel(
            username=username,
            password_hash=pw_hash,
            salt=salt,
            role=role.value,
            actor_label=label,
            failed_attempts=0,
            locked_until=None,
            created_at=self.clock.now().replace(tzinfo=None),
        )
        session.add(user)
        session.flush()

        record_audit_event(
            session=session,
            clock=self.clock,
            actor_label=creator_actor,
            action="CREATE_USER",
            entity="users",
            entity_id=str(user.id),
            after={"username": username, "role": role.value, "actor_label": label},
        )
        return user

    def authenticate(
        self,
        session: Session,
        username: str,
        secret: str,
    ) -> Tuple[Optional[UserModel], Optional[str]]:
        """Authenticate user against username and PIN/password, enforcing lockout rules.
        
        Returns (user, error_message).
        """
        user = session.query(UserModel).filter_by(username=username).first()
        if not user:
            return None, "Invalid username or credentials"

        # Check existing lockout
        is_locked, remaining_mins = check_user_lockout(
            user.failed_attempts, user.locked_until, self.clock
        )
        if is_locked:
            return None, f"Account is locked. Try again in {remaining_mins} minute(s)."

        # Verify secret
        if verify_pin_or_password(secret, user.password_hash, user.salt):
            # Success: reset failed attempts
            user.failed_attempts = 0
            user.locked_until = None
            session.flush()
            return user, None
        else:
            # Failed attempt
            user.failed_attempts += 1
            if user.failed_attempts >= 5:
                lock_duration = compute_lockout_duration_minutes(user.failed_attempts)
                lock_until_dt = (self.clock.now() + timedelta(minutes=lock_duration)).replace(tzinfo=None)
                user.locked_until = lock_until_dt
                session.flush()

                record_audit_event(
                    session=session,
                    clock=self.clock,
                    actor_label="System",
                    action="USER_LOCKOUT",
                    entity="users",
                    entity_id=str(user.id),
                    reason=f"Failed attempts reached {user.failed_attempts}. Locked for {lock_duration} mins.",
                )
                return None, f"Too many failed attempts. Account locked for {lock_duration} minutes."

            session.flush()
            remaining_attempts = 5 - user.failed_attempts
            return None, f"Invalid credentials. {remaining_attempts} attempt(s) remaining before lockout."
