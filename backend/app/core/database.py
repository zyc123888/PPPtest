from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings


engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base()


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> dict:
    from app.db_migrate import assert_database_current

    assert_database_current(engine)

    return {
        "database_backend": engine.url.get_backend_name(),
        "database_name": engine.url.database,
        "created_tables": [],
        "schema_changes": [],
    }
