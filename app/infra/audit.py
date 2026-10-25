"""Audit trail logging helper matching docs/SPEC.md Section B1 & B4."""

import json
from typing import Any, Optional
from sqlalchemy.orm import Session
from app.infra.clock import Clock
from app.infra.models import AuditLogModel


def record_audit_event(
    session: Session,
    clock: Clock,
    actor_label: str,
    action: str,
    entity: str,
    entity_id: Optional[str] = None,
    before: Optional[Any] = None,
    after: Optional[Any] = None,
    reason: Optional[str] = None,
) -> AuditLogModel:
    """Record an immutable entry in the audit_log table."""
    before_json = json.dumps(before, default=str) if before is not None else None
    after_json = json.dumps(after, default=str) if after is not None else None

    entry = AuditLogModel(
        at=clock.now().replace(tzinfo=None),  # Store naive UTC or clock local in DB
        actor_label=actor_label or "Operator",
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=before_json,
        after=after_json,
        reason=reason,
    )
    session.add(entry)
    return entry
