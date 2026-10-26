"""Application settings and configuration."""

from pathlib import Path
import json
import os
from typing import List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings:
    """Application configuration with environment overrides and defaults."""

    def __init__(self) -> None:
        self.APP_ENV: str = os.getenv("APP_ENV", "development")
        self.SECRET_KEY: str = os.getenv("SECRET_KEY", "srs-solar-insecure-secret-key-change-me")
        self.DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'srs_solar.db'}")

        # Plant defaults (Sunpro Antichettipalayam 10 MW)
        self.PLANT_NAME: str = os.getenv("PLANT_NAME", "Sunpro Antichettipalayam")
        self.PLANT_LATITUDE: float = float(os.getenv("PLANT_LATITUDE", "10.851319"))
        self.PLANT_LONGITUDE: float = float(os.getenv("PLANT_LONGITUDE", "77.909541"))
        self.PLANT_CAPACITY_MW: float = float(os.getenv("PLANT_CAPACITY_MW", "10.0"))
        self.TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Kolkata")

        # Target customer defaults
        self.TARGET_CUSTOMER_NAME: str = os.getenv("TARGET_CUSTOMER_NAME", "M/s. SRS KUMARAN INDIA PVT LTD")
        raw_aliases = os.getenv(
            "TARGET_CUSTOMER_ALIASES",
            '["M/s. SRS KUMARAN INDIA PVT LTD", "SRS KUMARAN INDIA PVT LTD", "SRS KUMARAN"]',
        )
        try:
            self.TARGET_CUSTOMER_ALIASES: List[str] = json.loads(raw_aliases)
        except Exception:
            self.TARGET_CUSTOMER_ALIASES = ["M/s. SRS KUMARAN INDIA PVT LTD", "SRS KUMARAN INDIA PVT LTD", "SRS KUMARAN"]
        self.TARGET_CUSTOMER_CAPACITY_MW: float = float(os.getenv("TARGET_CUSTOMER_CAPACITY_MW", "1.0"))

        # Validation thresholds
        self.EB_MF: int = int(os.getenv("EB_MF", "12"))
        self.BACKDATE_WARN_DAYS: int = int(os.getenv("BACKDATE_WARN_DAYS", "7"))
        self.MAX_DAILY_INVERTER_KWH: float = float(os.getenv("MAX_DAILY_INVERTER_KWH", "12000.0"))
        self.INVERTER_SPIKE_RATIO: float = float(os.getenv("INVERTER_SPIKE_RATIO", "1.3"))
        self.EB_RATIO_MIN: float = float(os.getenv("EB_RATIO_MIN", "0.95"))
        self.EB_RATIO_MAX: float = float(os.getenv("EB_RATIO_MAX", "1.00"))

        # Report & Month settings
        self.CLOSE_TIME: str = os.getenv("CLOSE_TIME", "00:05")
        self.GRACE_DAYS: int = int(os.getenv("GRACE_DAYS", "3"))
        self.DEBOUNCE_SECONDS: float = float(os.getenv("DEBOUNCE_SECONDS", "120.0"))
        self.REMARK_MODE: str = os.getenv("REMARK_MODE", "both")  # both, manual_only, auto_only
        self.WORKBOOK_MODE: str = os.getenv("WORKBOOK_MODE", "yearly")  # yearly, monthly
        self.DATE_FORMAT: str = os.getenv("DATE_FORMAT", "m/d/yyyy")
        export_copy_env = os.getenv("EXPORT_COPY_DIR")
        self.EXPORT_COPY_DIR: Optional[Path] = Path(export_copy_env) if export_copy_env else None

        # Third-party credentials
        self.OPEN_METEO_API_KEY: str = os.getenv("OPEN_METEO_API_KEY", "")
        self.GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

        # Directory structure
        self.DATA_DIR: Path = BASE_DIR / "data"
        self.WORKBOOKS_DIR: Path = self.DATA_DIR / "workbooks"
        self.REPORTS_DIR: Path = self.DATA_DIR / "reports"
        self.EVIDENCE_DIR: Path = self.DATA_DIR / "evidence"
        self.BACKUPS_DIR: Path = self.DATA_DIR / "backups"
        self.CACHE_INCOMING_DIR: Path = self.DATA_DIR / "cache" / "incoming"

    def ensure_directories(self) -> None:
        """Create required directories if they don't exist."""
        for path in [
            self.DATA_DIR,
            self.WORKBOOKS_DIR,
            self.REPORTS_DIR,
            self.EVIDENCE_DIR,
            self.BACKUPS_DIR,
            self.CACHE_INCOMING_DIR,
        ]:
            path.mkdir(parents=True, exist_ok=True)


# Global settings singleton
settings = Settings()
