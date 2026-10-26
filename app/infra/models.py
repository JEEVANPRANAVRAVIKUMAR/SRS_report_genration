"""Database ORM models matching docs/SPEC.md Section B4 & B14."""

from datetime import datetime
from typing import Any
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class PlantModel(Base):
    __tablename__ = "plants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    timezone = Column(String(50), nullable=False, default="Asia/Kolkata")
    capacity_mw = Column(Float, nullable=False, default=10.0)

    customers = relationship("CustomerModel", back_populates="plant")


class CustomerModel(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plant_id = Column(Integer, ForeignKey("plants.id"), nullable=False)
    display_name = Column(String(100), nullable=False)
    aliases = Column(Text, nullable=False, default="[]")  # JSON encoded list of aliases
    capacity_mw = Column(Float, nullable=False, default=1.0)
    is_target = Column(Boolean, nullable=False, default=True)

    plant = relationship("PlantModel", back_populates="customers")
    readings = relationship("ReadingModel", back_populates="customer")
    months = relationship("MonthModel", back_populates="customer")


class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    salt = Column(String(64), nullable=False)
    role = Column(String(20), nullable=False, default="OPERATOR")  # ADMIN, OPERATOR
    actor_label = Column(String(50), nullable=False, default="Operator")
    failed_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class UploadModel(Base):
    __tablename__ = "uploads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sha256 = Column(String(64), unique=True, nullable=False)
    evidence_path = Column(String(255), nullable=True)
    received_via = Column(String(20), nullable=False)  # SHARE, PICKER, CAMERA, MANUAL
    received_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    status = Column(String(20), nullable=False, default="PENDING_REVIEW")  # PENDING_REVIEW, ACCEPTED, REJECTED, SUPERSEDED
    engine = Column(String(30), nullable=False, default="MLKIT")
    parser_version = Column(String(20), nullable=True)
    prompt_version = Column(String(20), nullable=True)
    extraction = Column(Text, nullable=True)  # JSON string
    validation = Column(Text, nullable=True)  # JSON string

    readings = relationship("ReadingModel", back_populates="source_upload")


class ReadingModel(Base):
    __tablename__ = "readings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    report_date = Column(Date, nullable=False)
    inverter_kwh = Column(Float, nullable=False)
    eb_export_kwh = Column(Float, nullable=False)
    eb_6to10_kwh = Column(Float, nullable=False)
    reported_monthly_kwh = Column(Float, nullable=True)
    reported_yearly_kwh = Column(Float, nullable=True)
    inverter_availability_pct = Column(Float, nullable=True, default=100.0)
    grid_availability_pct = Column(Float, nullable=True, default=100.0)
    fault_text = Column(String(255), nullable=True, default="")
    plant_weather_text = Column(String(100), nullable=True, default="")
    plant_temp_c = Column(Float, nullable=True)
    manual_remark = Column(String(255), nullable=True, default="")
    auto_remark = Column(String(255), nullable=True, default="")
    source_upload_id = Column(Integer, ForeignKey("uploads.id"), nullable=True)
    entry_method = Column(String(20), nullable=False, default="MANUAL")  # IMAGE, MANUAL, IMPORT
    status = Column(String(20), nullable=False, default="ACTIVE")  # ACTIVE, VOID
    version = Column(Integer, nullable=False, default=1)
    actor_label = Column(String(50), nullable=False, default="Operator")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    customer = relationship("CustomerModel", back_populates="readings")
    source_upload = relationship("UploadModel", back_populates="readings")
    revisions = relationship("ReadingRevisionModel", back_populates="reading", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("customer_id", "report_date", name="uq_customer_report_date"),
    )


class ReadingRevisionModel(Base):
    __tablename__ = "reading_revisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reading_id = Column(Integer, ForeignKey("readings.id"), nullable=False)
    version = Column(Integer, nullable=False)
    snapshot = Column(Text, nullable=False)  # JSON string
    changed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    actor_label = Column(String(50), nullable=False)
    reason = Column(String(255), nullable=True)

    reading = relationship("ReadingModel", back_populates="revisions")


class OCRCorrectionModel(Base):
    __tablename__ = "ocr_corrections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    upload_id = Column(Integer, ForeignKey("uploads.id"), nullable=False)
    field = Column(String(50), nullable=False)
    recognised_value = Column(String(100), nullable=True)
    corrected_value = Column(String(100), nullable=True)
    at = Column(DateTime, nullable=False, default=datetime.utcnow)


class WeatherDailyModel(Base):
    __tablename__ = "weather_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plant_id = Column(Integer, ForeignKey("plants.id"), nullable=False)
    date = Column(Date, nullable=False)
    provider = Column(String(50), nullable=False, default="open-meteo")
    quality = Column(String(20), nullable=False, default="PROVISIONAL")  # PROVISIONAL, FINAL
    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    metrics = Column(Text, nullable=True)  # JSON
    sky_class = Column(String(50), nullable=True)
    rain_class = Column(String(50), nullable=True)
    remark_text = Column(String(100), nullable=True)
    raw_response = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("plant_id", "date", name="uq_plant_weather_date"),
    )


class MonthModel(Base):
    __tablename__ = "months"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    ym = Column(String(7), nullable=False)  # e.g. "2026-05"
    status = Column(String(20), nullable=False, default="OPEN")  # OPEN, CLOSED, LOCKED
    closed_at = Column(DateTime, nullable=True)
    locked_at = Column(DateTime, nullable=True)
    pdf_revision = Column(Integer, nullable=False, default=1)
    workbook_path = Column(String(255), nullable=True)

    customer = relationship("CustomerModel", back_populates="months")
    reports = relationship("ReportFileModel", back_populates="month")

    __table_args__ = (
        UniqueConstraint("customer_id", "ym", name="uq_customer_month_ym"),
    )


class ReportFileModel(Base):
    __tablename__ = "report_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    month_id = Column(Integer, ForeignKey("months.id"), nullable=False)
    kind = Column(String(20), nullable=False, default="PDF")
    revision = Column(Integer, nullable=False, default=1)
    path = Column(String(255), nullable=False)
    sha256 = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    exported_to_folder_at = Column(DateTime, nullable=True)
    reason = Column(String(50), nullable=False, default="CLOSE")  # CLOSE, LATE_ENTRY, MANUAL, POST_LOCK_AMENDMENT

    month = relationship("MonthModel", back_populates="reports")


class JobRunModel(Base):
    __tablename__ = "job_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_name = Column(String(50), nullable=False)
    period = Column(String(50), nullable=False)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="RUNNING")  # RUNNING, SUCCESS, FAILED
    message = Column(String(255), nullable=True)

    __table_args__ = (
        UniqueConstraint("job_name", "period", name="uq_job_period"),
    )


class AuditLogModel(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    at = Column(DateTime, nullable=False, default=datetime.utcnow)
    actor_label = Column(String(50), nullable=False)
    action = Column(String(50), nullable=False)
    entity = Column(String(50), nullable=False)
    entity_id = Column(String(50), nullable=True)
    before = Column(Text, nullable=True)  # JSON
    after = Column(Text, nullable=True)   # JSON
    reason = Column(String(255), nullable=True)


class NotificationModel(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    title = Column(String(100), nullable=False)
    message = Column(String(255), nullable=False)
    kind = Column(String(50), nullable=False, default="INFO")  # PDF_READY, REVISION_ADDED, ALERT, LATE_CLOSE
    ym = Column(String(7), nullable=True)
    is_read = Column(Boolean, nullable=False, default=False)
    action_url = Column(String(255), nullable=True)

