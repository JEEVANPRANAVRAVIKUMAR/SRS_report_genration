"""Unit test for Acceptance Criteria AC-02:
Import seed/may_2026.csv (1 to 18 May). Totals on 18 May: inverter 103065, EB 100740.
"""

from datetime import date
from pathlib import Path
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.domain.models import UserRole
from app.infra.clock import FakeClock
from app.infra.db import init_db
from app.infra.models import Base, ReadingModel
from app.services.csv_importer import import_csv_file
from app.services.reading_service import ReadingService


class TestAC02SeedImport(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        init_db(engine_override=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.clock = FakeClock()

    def test_import_seed_may_2026_and_verify_totals(self) -> None:
        csv_path = Path(__file__).resolve().parent.parent.parent / "seed" / "may_2026.csv"
        self.assertTrue(csv_path.exists(), f"Seed file not found at {csv_path}")

        with self.Session() as session:
            count, msgs = import_csv_file(
                file_path=csv_path,
                session=session,
                clock=self.clock,
                actor_label="AC-02 Tester",
                role=UserRole.ADMIN,
            )
            session.commit()

            # Verify 18 records imported (1 May to 18 May)
            self.assertEqual(count, 18, f"Expected 18 imported rows, got {count}")

            # Verify readings exist in database
            db_readings = session.query(ReadingModel).all()
            self.assertEqual(len(db_readings), 18)

            # Calculate running totals
            service = ReadingService(self.clock)
            totals = service.get_running_totals_for_month(session, 2026, 5)
            self.assertEqual(len(totals), 18)

            # Find 18 May 2026
            may_18 = next(t for t in totals if t.report_date == date(2026, 5, 18))

            # Non-negotiable AC-02 totals
            self.assertAlmostEqual(
                may_18.running_inverter_total,
                103065.0,
                places=2,
                msg=f"Expected inverter running total 103065.0, got {may_18.running_inverter_total}",
            )
            self.assertAlmostEqual(
                may_18.running_eb_total,
                100740.0,
                places=2,
                msg=f"Expected EB running total 100740.0, got {may_18.running_eb_total}",
            )


if __name__ == "__main__":
    unittest.main()
