"""Notification service for in-app alert badges, banners, and optional email delivery (SPEC Section B10)."""

from datetime import datetime
from pathlib import Path
from typing import List, Optional
from sqlalchemy.orm import Session
from app.infra.clock import Clock
from app.infra.models import NotificationModel


class NotificationService:
    """Manages in-app notifications and external notification dispatches."""

    def __init__(self, clock: Optional[Clock] = None) -> None:
        self.clock = clock

    def send_notification(
        self,
        session: Session,
        title: str,
        message: str,
        kind: str = "INFO",  # PDF_READY, REVISION_ADDED, ALERT, LATE_CLOSE
        ym: Optional[str] = None,
        action_url: Optional[str] = None,
        email_pdf_path: Optional[Path] = None,
    ) -> NotificationModel:
        """Create and persist an in-app notification banner/badge record."""
        now_dt = self.clock.now().replace(tzinfo=None) if self.clock else datetime.utcnow()
        notification = NotificationModel(
            created_at=now_dt,
            title=title,
            message=message,
            kind=kind,
            ym=ym,
            is_read=False,
            action_url=action_url,
        )
        session.add(notification)
        session.flush()

        # If email delivery is configured in settings and a PDF path is provided, send email here
        # (Stubbed safely for headless/standalone deployments)

        return notification

    def get_unread_notifications(self, session: Session) -> List[NotificationModel]:
        """Fetch all unread notifications ordered newest first."""
        return (
            session.query(NotificationModel)
            .filter_by(is_read=False)
            .order_by(NotificationModel.created_at.desc())
            .all()
        )

    def mark_as_read(self, session: Session, notification_id: int) -> Optional[NotificationModel]:
        """Mark a notification as read."""
        notif = session.query(NotificationModel).filter_by(id=notification_id).first()
        if notif:
            notif.is_read = True
            session.flush()
        return notif

    def get_all_notifications(self, session: Session, limit: int = 50) -> List[NotificationModel]:
        """Fetch recent notifications."""
        return (
            session.query(NotificationModel)
            .order_by(NotificationModel.created_at.desc())
            .limit(limit)
            .all()
        )
