"""Command Line Interface (CLI) for administration and operations.

Provides commands:
- init-db: Initialize database tables and plant/customer seeds
- create-admin: Create an administrative account with hashed credentials
- import-csv: Import historical data from CSV (e.g. seed/may_2026.csv)
- process-image: Ingest report image, extract evidence crop, and run extraction
- fetch-weather: Fetch and display Open-Meteo weather and remark for a date
- verify-ac01: Verify Acceptance Criteria AC-01 (Sample image extraction)
- verify-ac02: Verify Acceptance Criteria AC-02 (Seed CSV totals on 18 May)
- verify-ac03: Verify Acceptance Criteria AC-03 (22 May gap calculation)
- verify-ac12: Verify Acceptance Criteria AC-12 (Weather failure & refresh)
- verify-ac15: Verify Acceptance Criteria AC-15 (Privacy audit search)
- verify-ac18: Verify Acceptance Criteria AC-18 (Weather classification boundaries)
"""

import argparse
from datetime import date, datetime
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
from app.services.weather.client import RealOpenMeteoClient
from app.services.weather.service import WeatherService


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
    print(f"Plant Weather: {extraction.plant_weather_text.value}, {extraction.plant_temp_c.value}°C")


def cmd_fetch_weather(args: argparse.Namespace) -> None:
    clock = SystemClock()
    init_db()
    d = datetime.strptime(args.date, "%Y-%m-%d").date()

    with get_db() as session:
        weather_service = WeatherService(clock, client=RealOpenMeteoClient())
        remark, quality, summary = weather_service.get_or_fetch_weather(
            session=session,
            plant_id=1,
            report_date=d,
            force_refresh=args.refresh,
        )

        print(f"Weather for {d} (Plant Antichettipalayam):")
        print(f"  Auto Remark : {remark}")
        print(f"  Quality     : {quality.value}")
        if summary:
            print(f"  Mean Daytime Cloud Cover : {summary.mean_daytime_cloud_pct}%")
            print(f"  Total Solar Energy       : {summary.total_solar_energy_kwh_per_m2:.3f} kWh/m²")
            print(f"  Morning Solar (6-10am)   : {summary.morning_solar_energy_kwh_per_m2:.3f} kWh/m²")
            print(f"  24h Rain Total           : {summary.rain_24h_mm} mm")
            print(f"  Max Temperature          : {summary.max_temperature_c}°C")
        print("  Attribution: Weather data: Open-Meteo.com (CC BY 4.0)")


def cmd_verify_ac12(args: argparse.Namespace) -> None:
    from tests.unit.test_ac12_weather_failure_and_refresh import TestAC12WeatherFailureAndRefresh
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAC12WeatherFailureAndRefresh)
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if res.wasSuccessful() else 1)


def cmd_verify_ac18(args: argparse.Namespace) -> None:
    from tests.unit.test_ac18_weather_classification import TestAC18WeatherClassification
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAC18WeatherClassification)
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if res.wasSuccessful() else 1)


def cmd_close_month(args: argparse.Namespace) -> None:
    clock = SystemClock()
    init_db()
    from app.services.month_lifecycle import MonthLifecycleService
    y_str, m_str = args.ym.split("-")
    year, month = int(y_str), int(m_str)

    with get_db() as session:
        lifecycle = MonthLifecycleService(clock=clock)
        succ, msg = lifecycle.close_month(
            session=session,
            year=year,
            month=month,
            is_late_close=args.late,
            actor_label=args.actor_label or "CLI Admin",
            reason=args.reason or "CLI close-month command",
        )
        session.commit()
        print(f"Result: {msg}")


def cmd_reopen_month(args: argparse.Namespace) -> None:
    clock = SystemClock()
    init_db()
    from app.services.month_lifecycle import MonthLifecycleService
    y_str, m_str = args.ym.split("-")
    year, month = int(y_str), int(m_str)

    with get_db() as session:
        lifecycle = MonthLifecycleService(clock=clock)
        succ, msg = lifecycle.admin_reopen_month(
            session=session,
            year=year,
            month=month,
            actor_label=args.actor_label or "CLI Admin",
            reason=args.reason,
        )
        session.commit()
        print(f"Result: {msg}")


def cmd_regenerate_pdf(args: argparse.Namespace) -> None:
    clock = SystemClock()
    init_db()
    from app.services.month_lifecycle import MonthLifecycleService
    y_str, m_str = args.ym.split("-")
    year, month = int(y_str), int(m_str)

    with get_db() as session:
        lifecycle = MonthLifecycleService(clock=clock)
        rep = lifecycle.admin_regenerate_pdf(
            session=session,
            year=year,
            month=month,
            actor_label=args.actor_label or "CLI Admin",
            reason=args.reason or "CLI regenerate-pdf command",
        )
        session.commit()
        print(f"Regenerated PDF: {rep.path} (SHA-256: {rep.sha256}, Revision: {rep.revision})")


def cmd_run_scheduler_check(args: argparse.Namespace) -> None:
    clock = SystemClock()
    init_db()
    from app.services.scheduler import SolarScheduler
    scheduler = SolarScheduler(clock=clock)
    results = scheduler.run_catchup_at_startup()
    print(f"Scheduler transition check completed: {results}")


def cmd_verify_ac07(args: argparse.Namespace) -> None:
    from tests.unit.test_ac07_month_close import TestAC07MonthClose
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAC07MonthClose)
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if res.wasSuccessful() else 1)


def cmd_verify_ac08(args: argparse.Namespace) -> None:
    from tests.unit.test_ac08_late_entry_debounce import TestAC08LateEntryDebounce
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAC08LateEntryDebounce)
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if res.wasSuccessful() else 1)


def cmd_verify_ac09(args: argparse.Namespace) -> None:
    from tests.unit.test_ac09_catchup_startup import TestAC09CatchupStartup
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAC09CatchupStartup)
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if res.wasSuccessful() else 1)


def cmd_verify_ac10(args: argparse.Namespace) -> None:
    from tests.unit.test_ac10_month_locking import TestAC10MonthLocking
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAC10MonthLocking)
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if res.wasSuccessful() else 1)


def cmd_verify_ac11(args: argparse.Namespace) -> None:
    from tests.unit.test_ac11_utc_clock_close import TestAC11UTCClockClose
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAC11UTCClockClose)
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if res.wasSuccessful() else 1)


def cmd_backup(args: argparse.Namespace) -> None:
    clock = SystemClock()
    init_db()
    from app.services.backup import BackupService
    backup_service = BackupService(clock=clock)
    with get_db() as session:
        b_path = backup_service.create_backup(
            session=session,
            label=args.label,
            actor_label=args.actor_label or "CLI Admin",
        )
        session.commit()
        print(f"Backup created successfully: {b_path}")


def cmd_restore(args: argparse.Namespace) -> None:
    clock = SystemClock()
    init_db()
    from app.services.backup import BackupService
    backup_service = BackupService(clock=clock)
    target = settings.BACKUPS_DIR / args.target
    if not target.exists():
        target = Path(args.target)
    if not target.exists():
        print(f"Backup not found: {args.target}", file=sys.stderr)
        sys.exit(1)

    print(f"Restoring from backup: {target}...")
    res = backup_service.restore_backup(target)
    print(f"Restoration complete: {res}")


def cmd_list_backups(args: argparse.Namespace) -> None:
    from app.services.backup import BackupService
    backup_service = BackupService()
    backups = backup_service.list_backups()
    print(f"Found {len(backups)} backups in {settings.BACKUPS_DIR}:")
    for b in backups:
        print(f"  - {b['directory']} ({b['created_at']}) • WB: {b['workbooks_count']}, Rep: {b['reports_count']}")


def cmd_serve(args: argparse.Namespace) -> None:
    from app.web.app import create_app
    from wsgiref.simple_server import make_server
    port = args.port or int(os.getenv("PORT", "8000"))
    app = create_app()
    print(f"Starting SRS Solar Log Web Server at http://0.0.0.0:{port}...")
    server = make_server("0.0.0.0", port, app)
    server.serve_forever()


def cmd_verify_ac19(args: argparse.Namespace) -> None:
    from tests.unit.test_ac19_backup_restore import TestAC19BackupRestore
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAC19BackupRestore)
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if res.wasSuccessful() else 1)


def cmd_verify_ac20(args: argparse.Namespace) -> None:
    from tests.unit.test_ac20_security_csrf_rbac import TestAC20SecurityCSRFRBAC
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAC20SecurityCSRFRBAC)
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

    p_w = subparsers.add_parser("fetch-weather", help="Fetch Open-Meteo weather for a date")
    p_w.add_argument("date", help="YYYY-MM-DD")
    p_w.add_argument("--refresh", action="store_true", help="Force refresh even if cached")

    # Month Lifecycle CLI Commands
    p_close = subparsers.add_parser("close-month", help="Close a month manually (Admin)")
    p_close.add_argument("--ym", required=True, help="YYYY-MM (e.g. 2026-05)")
    p_close.add_argument("--late", action="store_true", help="Mark as late close")
    p_close.add_argument("--reason", default="Manual admin close", help="Reason for close")
    p_close.add_argument("--actor-label", default="Admin", help="Actor label")

    p_reopen = subparsers.add_parser("reopen-month", help="Reopen a closed or locked month (Admin)")
    p_reopen.add_argument("--ym", required=True, help="YYYY-MM (e.g. 2026-05)")
    p_reopen.add_argument("--reason", required=True, help="Written reason for reopening (mandatory)")
    p_reopen.add_argument("--actor-label", default="Admin", help="Actor label")

    p_regen = subparsers.add_parser("regenerate-pdf", help="Regenerate official PDF for a month")
    p_regen.add_argument("--ym", required=True, help="YYYY-MM")
    p_regen.add_argument("--reason", default="Admin PDF regeneration", help="Reason")
    p_regen.add_argument("--actor-label", default="Admin", help="Actor label")

    subparsers.add_parser("run-scheduler-check", help="Run due lifecycle transitions check")

    # Operations & Backup Commands (SPEC B14)
    p_bk = subparsers.add_parser("backup", help="Create consistent SQLite backup and report archive")
    p_bk.add_argument("--label", default="manual", help="Backup label")
    p_bk.add_argument("--actor-label", default="Admin", help="Actor label")

    p_res = subparsers.add_parser("restore", help="Restore database and reports from backup")
    p_res.add_argument("--from", dest="target", required=True, help="Backup folder name or path")
    p_res.add_argument("--reason", default="Manual CLI restore", help="Reason for restore")

    subparsers.add_parser("list-backups", help="List available backups")

    p_srv = subparsers.add_parser("serve", help="Run Web Server")
    p_srv.add_argument("--port", type=int, default=8000, help="Port to listen on")

    # Verification Commands
    subparsers.add_parser("verify-ac07", help="Verify AC-07 (Month close at 00:05 IST on 1st)")
    subparsers.add_parser("verify-ac08", help="Verify AC-08 (Late entry debounce & rev 2)")
    subparsers.add_parser("verify-ac09", help="Verify AC-09 (Startup catch-up & late close)")
    subparsers.add_parser("verify-ac10", help="Verify AC-10 (Month locking & post-lock amendment)")
    subparsers.add_parser("verify-ac11", help="Verify AC-11 (UTC clock timezone trigger)")
    subparsers.add_parser("verify-ac12", help="Verify AC-12 (Weather outage & refresh)")
    subparsers.add_parser("verify-ac18", help="Verify AC-18 (Weather classification boundaries)")
    subparsers.add_parser("verify-ac19", help="Verify AC-19 (Backup & restore round-trip hashes)")
    subparsers.add_parser("verify-ac20", help="Verify AC-20 (CSRF protection & role matrix)")

    args = parser.parse_args()

    if args.command == "init-db":
        cmd_init_db(args)
    elif args.command == "create-admin":
        cmd_create_admin(args)
    elif args.command == "import-csv":
        cmd_import_csv(args)
    elif args.command == "process-image":
        cmd_process_image(args)
    elif args.command == "fetch-weather":
        cmd_fetch_weather(args)
    elif args.command == "close-month":
        cmd_close_month(args)
    elif args.command == "reopen-month":
        cmd_reopen_month(args)
    elif args.command == "regenerate-pdf":
        cmd_regenerate_pdf(args)
    elif args.command == "run-scheduler-check":
        cmd_run_scheduler_check(args)
    elif args.command == "backup":
        cmd_backup(args)
    elif args.command == "restore":
        cmd_restore(args)
    elif args.command == "list-backups":
        cmd_list_backups(args)
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "verify-ac07":
        cmd_verify_ac07(args)
    elif args.command == "verify-ac08":
        cmd_verify_ac08(args)
    elif args.command == "verify-ac09":
        cmd_verify_ac09(args)
    elif args.command == "verify-ac10":
        cmd_verify_ac10(args)
    elif args.command == "verify-ac11":
        cmd_verify_ac11(args)
    elif args.command == "verify-ac12":
        cmd_verify_ac12(args)
    elif args.command == "verify-ac18":
        cmd_verify_ac18(args)
    elif args.command == "verify-ac19":
        cmd_verify_ac19(args)
    elif args.command == "verify-ac20":
        cmd_verify_ac20(args)


if __name__ == "__main__":
    main()


