from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args, future=True)
    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _configure_sqlite(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
    return engine


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, class_=Session)


def init_db() -> None:
    from app import models  # noqa: F401

    get_settings().ensure_directories()
    Base.metadata.create_all(bind=engine)
    if engine.url.drivername.startswith("sqlite"):
        columns = {column["name"] for column in inspect(engine).get_columns("reports")}
        if "batch_id" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE reports ADD COLUMN batch_id VARCHAR(36)"))
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_reports_batch_id ON reports (batch_id)"))


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
