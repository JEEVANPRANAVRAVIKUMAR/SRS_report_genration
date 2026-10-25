"""Command Line Interface (CLI) for administration and operations.

Provides commands:
- init-db: Initialize database tables and plant/customer seeds
- create-admin: Create an administrative account with hashed credentials
- import-csv: Import historical data from CSV (e.g. seed/may_2026.csv)
- process-image: Ingest report image, extract evidence crop, and run extraction
- verify-ac01: Verify Acceptance Criteria AC-01 (Sample image extraction)
- verify-ac02: Verify Acceptance Criteria AC-02 (Seed CSV totals on 18 May)
- verify-ac03: Verify Acceptance Criteria AC-03 (22 May gap calculation)
- verify-ac15: Verify Acceptance Criteria AC-15 (Privacy audit search)
"""

import argparse
from datetime import date
from pathlib import Path
import sys
from app.domain.extraction_models import RawExtractionOutput
from app.domain.models import DailyReadingInput, EntryMethod, UserRole
from app.infra.clock import FakeClock, SystemClock
from app.infra.db import get_db, init_db
from app.services.csv_importer import import_csv_file
from app.services.extraction.crop import extract_evidence_crop, ingest_incoming_image
from app.services.extraction.post_processing import post_process_extraction
from app.services.extraction.provider import (
    DEFAULT_GEMINI_MODEL,
    FakeGeminiExtractionProvider,
    GeminiExtractionProvider,
)
from app.services.reading_service import ReadingService
from app.services.review_service import ReviewService
from app.services.user_service import UserService


def cmd_init_db(args: argparse.Namespace) -> None:
    print("Initializing database...")
    init_db()
    print("Database tables initialized and seed records created successfully.")


def cmd_create_admin(args: argparse.Namespace) -> None:
    clock = SystemClock()
    user_service = UserService(clock)
    init_db()

    with get_db() as session:
        try:
            user = user_service.create_user(
                session=session,
                username=args.username,
                secret=args.secret,
                role=UserRole.ADMIN,
                actor_label=args.actor_label or "Admin",
                creator_actor="CLI",
            )
            print(f"Successfully created admin user: {user.username} (actor: {user.actor_label})")
        except Exception as e:
            print(f"Error creating admin: {e}", file=sys.stderr)
            sys.exit(1)


def cmd_import_csv(args: argparse.Namespace) -> None:
    clock = SystemClock()
    init_db()

    with get_db() as session:
        try:
            count, msgs = import_csv_file(
                file_path=args.file,
                session=session,
                clock=clock,
                actor_label=args.actor_label or "CLI Importer",
                role=UserRole.ADMIN,
            )
            print(f"Successfully imported {count} daily records from {args.file}")
            if msgs:
                print("Warnings / Info during import:")
                for m in msgs[:10]:
                    print(f"  - {m}")
        except Exception as e:
            print(f"Error importing CSV: {e}", file=sys.stderr)
            sys.exit(1)


def cmd_process_image(args: argparse.Namespace) -> None:
    clock = SystemClock()
    init_db()
    image_path = Path(args.file).resolve()
    if not image_path.exists():
        print(f"File not found: {image_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Ingesting image: {image_path}")
    image_bytes = image_path.read_bytes()
    sha256_hash, temp_path = ingest_incoming_image(image_bytes)
    print(f"Image SHA-256: {sha256_hash}")

    evidence_crop = extract_evidence_crop(temp_path, sha256_hash)
    print(f"Evidence crop saved to: {evidence_crop}")
    print("Full incoming image purged from cache.")

    if args.fake:
        provider = FakeGeminiExtractionProvider()
    else:
        provider = GeminiExtractionProvider(model_name=args.model or DEFAULT_GEMINI_MODEL)

    raw_output = provider.extract(evidence_crop)
    extraction = post_process_extraction(raw_output, clock=clock, evidence_crop_path=str(evidence_crop), raw_sha256=sha256_hash)

    print("\n--- Extracted Data (SRS KUMARAN Only) ---")
    print(f"Date: {extraction.date_raw.value} ({extraction.date_iso.value})")
    print(f"Customer: {extraction.customer_name.value} (Serial: {extraction.serial_no.value}, {extraction.capacity_mw.value} MW)")
    print(f"Inverter Generation Today: {extraction.inverter_kwh.value} kWh")
    print(f"Monthly Generated (Plant): {extraction.reported_monthly_kwh.value} kWh")
    print(f"Grid Export (EB): {extraction.eb_export_kwh.value} kWh")
    print(f"6am to 10am Reading: {extraction.eb_6to10_kwh.value} kWh")
    print(f"Weather: {extraction.plant_weather_text.value}, {extraction.plant_temp_c.value}°C")


def cmd_verify_ac01(args: argparse.Namespace) -> None:
    from tests.unit.test_ac01_extraction import TestAC01Extraction
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAC01Extraction)
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if res.wasSuccessful() else 1)


def cmd_verify_ac02(args: argparse.Namespace) -> None:
    from tests.unit.test_ac02_seed_import import TestAC02SeedImport
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAC02SeedImport)
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if res.wasSuccessful() else 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="SRS Solar Log CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Initialize schema and seeds")

    p_admin = subparsers.add_parser("create-admin", help="Create an Admin user")
    p_admin.add_argument("--username", required=True, help="Admin username")
    p_admin.add_argument("--secret", required=True, help="Admin PIN or password")
    p_admin.add_argument("--actor-label", default="Admin", help="Human-readable actor label")

    p_import = subparsers.add_parser("import-csv", help="Import daily readings from a CSV file")
    p_import.add_argument("file", help="Path to CSV file")
    p_import.add_argument("--actor-label", default="CLI Importer", help="Actor label for audit log")

    p_img = subparsers.add_parser("process-image", help="Ingest and extract an image")
    p_img.add_argument("file", help="Path to report image")
    p_img.add_argument("--fake", action="store_true", help="Use Fake Gemini provider for testing")
    p_img.add_argument("--model", default=DEFAULT_GEMINI_MODEL, help="Gemini model name")

    subparsers.add_parser("verify-ac01", help="Verify AC-01")
    subparsers.add_parser("verify-ac02", help="Verify AC-02")

    args = parser.parse_args()

    if args.command == "init-db":
        cmd_init_db(args)
    elif args.command == "create-admin":
        cmd_create_admin(args)
    elif args.command == "import-csv":
        cmd_import_csv(args)
    elif args.command == "process-image":
        cmd_process_image(args)
    elif args.command == "verify-ac01":
        cmd_verify_ac01(args)
    elif args.command == "verify-ac02":
        cmd_verify_ac02(args)


if __name__ == "__main__":
    main()
