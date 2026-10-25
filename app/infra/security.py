"""Security, hashing, and lockout policy matching docs/SPEC.md B2 & B13."""

from datetime import datetime, timedelta
import hashlib
import hmac
import os
import secrets
from typing import Optional, Tuple
from app.infra.clock import Clock


def generate_salt(length: int = 32) -> str:
    """Generate a random hex salt."""
    return secrets.token_hex(length)


def hash_pin_or_password(secret: str, salt: str | None = None) -> Tuple[str, str]:
    """Slow hash of a PIN or password using PBKDF2-HMAC-SHA256 with 100,000 iterations."""
    if salt is None:
        salt = generate_salt()
    key = hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        salt.encode("utf-8"),
        100_000,
    )
    return key.hex(), salt


def verify_pin_or_password(secret: str, expected_hash: str, salt: str) -> bool:
    """Verify a PIN or password against its hash and salt using constant-time comparison."""
    key = hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        salt.encode("utf-8"),
        100_000,
    )
    return hmac.compare_digest(key.hex(), expected_hash)


def compute_lockout_duration_minutes(failed_attempts: int) -> int:
    """Compute lockout delay in minutes: 5 wrong attempts -> 15 mins, doubling each time.
    
    5 attempts -> 15 mins
    6 attempts -> 30 mins
    7 attempts -> 60 mins
    """
    if failed_attempts < 5:
        return 0
    exponent = failed_attempts - 5
    return 15 * (2 ** exponent)


def check_user_lockout(
    failed_attempts: int,
    locked_until: Optional[datetime],
    clock: Clock,
) -> Tuple[bool, Optional[int]]:
    """Check if the user is currently locked out.
    
    Returns (is_locked, remaining_minutes).
    """
    if locked_until is None:
        return False, None

    now = clock.now()
    # Normalize tz
    if locked_until.tzinfo is None:
        locked_until_tz = locked_until.replace(tzinfo=clock.timezone)
    else:
        locked_until_tz = locked_until.astimezone(clock.timezone)

    if now < locked_until_tz:
        diff_seconds = (locked_until_tz - now).total_seconds()
        remaining_minutes = max(1, int(diff_seconds // 60) + 1)
        return True, remaining_minutes

    return False, None
