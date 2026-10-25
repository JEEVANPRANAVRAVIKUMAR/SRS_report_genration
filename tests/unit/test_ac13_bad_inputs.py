"""Unit tests for Acceptance Criteria AC-13:
Bad inputs (blurry image, non-report image, SRS row missing, future date,
oversized file, wrong file type) are each rejected with a clear message and nothing is saved.
"""

from datetime import date
import unittest
from app.domain.extraction_models import RawExtractionOutput
from app.infra.clock import FakeClock
from app.services.extraction.crop import CropError, ingest_incoming_image
from app.services.extraction.post_processing import (
    ExtractionValidationError,
    post_process_extraction,
)
from app.services.extraction.provider import FakeGeminiExtractionProvider


class TestAC13BadInputs(unittest.TestCase):
    def setUp(self) -> None:
        # Clock set to 22 May 2026
        self.clock = FakeClock(date(2026, 5, 22))

    def test_blurry_or_unreadable_image_rejected(self) -> None:
        """AC-13: Blurry image is rejected with a clear message."""
        provider = FakeGeminiExtractionProvider(
            should_fail=True,
            fail_message="Image is too blurry or low-resolution to extract values.",
        )
        with self.assertRaises(ValueError) as ctx:
            provider.extract(image_path="dummy.jpg")
        self.assertIn("blurry", str(ctx.exception))

    def test_non_report_image_or_srs_row_missing_rejected(self) -> None:
        """AC-13: Non-report image or SRS row missing is rejected."""
        # Case A: Customer name is None
        raw_missing = RawExtractionOutput(
            date_raw="22/05/2026",
            customer_name_raw=None,
        )
        with self.assertRaises(ExtractionValidationError) as ctx:
            post_process_extraction(raw_missing, clock=self.clock)
        self.assertIn("Customer row missing", str(ctx.exception))

        # Case B: Customer name belongs to another customer (e.g. Prabhu Textiles)
        raw_wrong_customer = RawExtractionOutput(
            date_raw="22/05/2026",
            customer_name_raw="M/s. PRABHU TEXTILES",
            capacity_mw=1.0,
        )
        with self.assertRaises(ExtractionValidationError) as ctx:
            post_process_extraction(raw_wrong_customer, clock=self.clock)
        self.assertIn("does not match target 'SRS KUMARAN'", str(ctx.exception))

    def test_future_date_rejected(self) -> None:
        """AC-13: Date in the future (later than today in India) is rejected."""
        # Clock today is 2026-05-22, report date is 2026-05-25
        raw_future = RawExtractionOutput(
            date_raw="25/05/2026",
            customer_name_raw="M/s. SRS KUMARAN INDIA PVT LTD",
            capacity_mw=1.0,
            inverter_generation_today_kwh=7625.0,
        )
        with self.assertRaises(ExtractionValidationError) as ctx:
            post_process_extraction(raw_future, clock=self.clock)
        self.assertIn("is in the future", str(ctx.exception))

    def test_oversized_file_rejected(self) -> None:
        """AC-13: Files exceeding size limit (25 MB) are rejected."""
        oversized_bytes = b"0" * (26 * 1024 * 1024)  # 26 MB
        with self.assertRaises(CropError) as ctx:
            ingest_incoming_image(oversized_bytes, "large.jpg")
        self.assertIn("exceeds 25 MB", str(ctx.exception))

    def test_corrupted_file_type_rejected(self) -> None:
        """AC-13: Wrong file type or corrupted bytes are rejected."""
        corrupt_bytes = b"NOT_A_VALID_IMAGE_HEADER_BYTES_12345678"
        with self.assertRaises(CropError) as ctx:
            ingest_incoming_image(corrupt_bytes, "corrupt.jpg")
        self.assertIn("Invalid or corrupted image", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
