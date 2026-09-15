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
        migrations = {
            "batch_id": "ALTER TABLE reports ADD COLUMN batch_id VARCHAR(36)",
            "checksum_sha256": "ALTER TABLE reports ADD COLUMN checksum_sha256 VARCHAR(64)",
            "index_status": "ALTER TABLE reports ADD COLUMN index_status VARCHAR(20) NOT NULL DEFAULT 'pending'",
            "chunk_count": "ALTER TABLE reports ADD COLUMN chunk_count INTEGER NOT NULL DEFAULT 0",
            "indexed_at": "ALTER TABLE reports ADD COLUMN indexed_at DATETIME",
        }
        with engine.begin() as connection:
            for column, statement in migrations.items():
                if column not in columns:
                    connection.execute(text(statement))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_reports_batch_id ON reports (batch_id)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_reports_checksum_sha256 ON reports (checksum_sha256)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_reports_index_status ON reports (index_status)"))


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
