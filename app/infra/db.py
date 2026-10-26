"""Database engine, session management, and initialization."""

from contextlib import contextmanager
import json
from pathlib import Path
from typing import Any, Generator
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from app.infra.clock import KOLKATA_TZ
from app.infra.models import Base, CustomerModel, PlantModel
from app.infra.settings import settings


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
    """Enforce foreign key constraints on SQLite."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine(db_url: str | None = None) -> Engine:
    """Create database engine."""
    url = db_url or settings.DATABASE_URL
    if url.startswith("sqlite"):
        # Make sure parent directory exists
        if "///" in url:
            db_path = url.split("///")[1]
            if not db_path.startswith(":memory:"):
                Path(db_path).resolve().parent.mkdir(parents=True, exist_ok=True)
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url)


# Default engine and sessionmaker
engine = get_engine()
SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_session() -> Session:
    """Create and return a new Session instance."""
    return SessionFactory()



@contextmanager
def get_db(session_override: Session | None = None) -> Generator[Session, None, None]:
    """Provide a transactional database session."""
    if session_override is not None:
        yield session_override
        return

    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(engine_override: Engine | None = None) -> None:
    """Initialize schema and seed plant and target customer."""
    settings.ensure_directories()
    eng = engine_override or engine
    Base.metadata.create_all(bind=eng)

    # Seed initial plant and customer records if not present
    LocalSession = sessionmaker(bind=eng)
    with LocalSession() as session:
        plant = session.query(PlantModel).filter_by(name=settings.PLANT_NAME).first()
        if not plant:
            plant = PlantModel(
                name=settings.PLANT_NAME,
                latitude=settings.PLANT_LATITUDE,
                longitude=settings.PLANT_LONGITUDE,
                timezone=settings.TIMEZONE,
                capacity_mw=settings.PLANT_CAPACITY_MW,
            )
            session.add(plant)
            session.flush()

        customer = session.query(CustomerModel).filter_by(display_name=settings.TARGET_CUSTOMER_NAME).first()
        if not customer:
            customer = CustomerModel(
                plant_id=plant.id,
                display_name=settings.TARGET_CUSTOMER_NAME,
                aliases=json.dumps(settings.TARGET_CUSTOMER_ALIASES),
                capacity_mw=settings.TARGET_CUSTOMER_CAPACITY_MW,
                is_target=True,
            )
            session.add(customer)

        session.commit()
