"""
SQLAlchemy engine/session setup. SQLite locally (DATABASE_URL in .env),
portable to Postgres for a hosted deployment (e.g. postgresql+psycopg://...)
without changing any repository/service code.

NO ALEMBIC YET: init_db() below is create_all() + a schema_version marker
row -- a documented PLACEHOLDER, not a migration strategy. There is no real
device data to protect yet. Alembic (or hand-written ALTER TABLE/backfill
scripts) must be added before any real deployment accumulates device history.
"""
import threading
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from config import DATABASE_URL

SCHEMA_VERSION = 1

_is_sqlite = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    future=True,
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        # WAL + a busy timeout are required once a background worker thread and
        # request-handling threads write concurrently -- without them SQLite's
        # default rollback-journal mode intermittently raises "database is locked".
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# Each request gets its own Session (via get_db, a FastAPI dependency); the
# background worker thread and demo/test helpers get their own via
# session_scope(). A Session is never shared across threads.
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

_init_lock = threading.Lock()


def get_db():
    """FastAPI dependency: one Session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    """For code outside a FastAPI request: the worker thread, demo/test helpers."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Creates tables if they don't exist yet. Idempotent -- safe to call on every startup."""
    from db_models import Base, SchemaVersion  # local import: avoids a circular import at module load time

    with _init_lock:
        Base.metadata.create_all(bind=engine)
        with session_scope() as db:
            row = db.get(SchemaVersion, 1)
            if row is None:
                db.add(SchemaVersion(id=1, version=SCHEMA_VERSION))
                db.commit()
