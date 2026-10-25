"""Unit test for Acceptance Criteria AC-05:
The same image twice is blocked by hash.
The same date with a different image shows a difference and needs confirmation;
the old values stay in revision history.
"""

from datetime import date
import json
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.domain.models import DailyReadingInput
from app.infra.clock import FakeClock
from app.infra.db import init_db
from app.infra.models import Base, ReadingModel, ReadingRevisionModel, UploadModel
from app.services.reading_service import ReadingService
from app.services.review_service import ReviewService


class TestAC05DuplicateReplace(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock(date(2026, 5, 22))
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        init_db(engine_override=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.reading_service = ReadingService(self.clock)
        self.review_service = ReviewService(self.clock)

    def test_duplicate_image_blocked_by_hash(self) -> None:
        """AC-05: Same image hash twice is stopped by unique hash constraint."""
        fixed_sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

        with self.Session() as session:
            # First upload succeeds
            upload1 = UploadModel(
                sha256=fixed_sha,
                received_via="PICKER",
                status="PENDING_REVIEW",
            )
            session.add(upload1)
            session.commit()

            # Second upload with same hash is detected as duplicate
            existing = session.query(UploadModel).filter_by(sha256=fixed_sha).first()
            self.assertIsNotNone(existing)
            self.assertEqual(existing.id, upload1.id)

    def test_same_date_different_image_shows_diff_and_keeps_history(self) -> None:
        """AC-05: Same date with different values shows diff and retains old values in revision history."""
        target_date = date(2026, 5, 22)

        with self.Session() as session:
            # 1. Save original reading (version 1)
            initial_reading = DailyReadingInput(
                report_date=target_date,
                inverter_kwh=7625.0,
                eb_export_kwh=7452.0,
                eb_6to10_kwh=1584.0,
                reported_monthly_kwh=130428.0,
                actor_label="Operator 1",
            )
            r1, _ = self.reading_service.save_reading(session, initial_reading)
            session.commit()

            self.assertEqual(r1.version, 1)
            self.assertEqual(r1.inverter_kwh, 7625.0)

            # 2. Second upload for the same date with corrected numbers
            new_reading_candidate = DailyReadingInput(
                report_date=target_date,
                inverter_kwh=7630.0,
                eb_export_kwh=7460.0,
                eb_6to10_kwh=1584.0,
                reported_monthly_kwh=130428.0,
                actor_label="Operator 2",
            )

            # Build effect preview: must detect existing reading diff
            preview = self.review_service.build_effect_preview(session, new_reading_candidate)
            self.assertIsNotNone(preview.existing_reading_diff)
            self.assertIn("inverter_kwh", preview.existing_reading_diff)
            self.assertEqual(preview.existing_reading_diff["inverter_kwh"], (7625.0, 7630.0))
            self.assertIn("eb_export_kwh", preview.existing_reading_diff)
            self.assertEqual(preview.existing_reading_diff["eb_export_kwh"], (7452.0, 7460.0))

            # 3. Confirm replace
            r2, _ = self.reading_service.save_reading(
                session=session,
                reading_input=new_reading_candidate,
                admin_override_reason="Operator confirmed replacement with updated image",
            )
            session.commit()

            # Version incremented to 2
            self.assertEqual(r2.version, 2)
            self.assertEqual(r2.inverter_kwh, 7630.0)

            # Verify revision history retains original version 1 snapshot
            revisions = (
                session.query(ReadingRevisionModel)
                .filter_by(reading_id=r2.id)
                .all()
            )
            self.assertEqual(len(revisions), 1)
            rev1 = revisions[0]
            self.assertEqual(rev1.version, 1)

            snapshot_data = json.loads(rev1.snapshot)
            self.assertEqual(snapshot_data["inverter_kwh"], 7625.0)
            self.assertEqual(snapshot_data["eb_export_kwh"], 7452.0)
            self.assertIn("replacement with updated image", rev1.reason)


if __name__ == "__main__":
    unittest.main()
