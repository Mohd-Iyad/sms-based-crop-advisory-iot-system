"""
ORM table definitions (SQLAlchemy declarative). Named db_models.py, not
models.py, so it doesn't collide with models.py's Pydantic SensorData (the
incoming-payload shape) -- these are the persisted-state shape.

Design notes (see the Phase 1 plan for the full reasoning):

- DeviceAlertState is the CHEAP, indexed-lookup "is this code currently
  active, and when did we last notify for it" table (mirrors the old
  state_manager in-memory dict exactly: active_codes + last_sent). AlertEvent
  is a separate, append-only AUDIT row, inserted only when something is
  actually new -- so the hot cooldown check never has to scan history.

- Device carries the current "dashboard snapshot" directly as columns
  (last_facts_json / last_alert_codes_json / last_delivery_json /
  last_delivery_at / last_reading_at) rather than a joined table, so the
  dashboard's hot, auto-refreshing read path is a single row fetch, not a join.

- Reading.boot_id is nullable, and UNIQUE(device_id, boot_id, sequence) is
  INERT for all current firmware traffic: SQL treats NULL != NULL, so two
  legacy readings (boot_id=NULL) never collide on this constraint. Dedup for
  those devices is enforced by the sequence-heuristic in repositories/devices.py
  (ported from the old REBOOT_SEQUENCE_DROP logic), not by this constraint.
  The constraint exists so future firmware that DOES send boot_id gets real
  DB-level dedup for free.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class SchemaVersion(Base):
    __tablename__ = "schema_version"
    id = Column(Integer, primary_key=True)
    version = Column(Integer, nullable=False)


class Device(Base):
    __tablename__ = "devices"

    device_id = Column(String(64), primary_key=True)
    device_name = Column(String(128), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    # NULL means "no per-device secret provisioned yet -- fall back to the
    # global EXPECTED_DEVICE_KEY" (dev-mode compatible with unmodified firmware).
    secret_hash = Column(String(128), nullable=True)

    first_seen = Column(DateTime, nullable=False, default=datetime.now)
    last_seen = Column(DateTime, nullable=True)
    last_boot_id = Column(String(64), nullable=True)
    last_sequence = Column(Integer, nullable=False, default=-1)
    status = Column(String(32), nullable=False, default="unknown")

    # Dashboard snapshot, kept as columns (see module docstring).
    last_reading_at = Column(DateTime, nullable=True)
    moisture_state = Column(String(16), nullable=True)  # "low"/"normal"/"high"/None, for hysteresis
    last_facts_json = Column(Text, nullable=True)
    last_alert_codes_json = Column(Text, nullable=True)
    last_delivery_json = Column(Text, nullable=True)
    last_delivery_at = Column(DateTime, nullable=True)


class Reading(Base):
    __tablename__ = "readings"
    __table_args__ = (
        UniqueConstraint("device_id", "boot_id", "sequence", name="uq_reading_device_boot_sequence"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(64), ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False, index=True)
    boot_id = Column(String(64), nullable=True)  # NULL for firmware that doesn't send one yet (see module docstring)
    sequence = Column(Integer, nullable=False)
    received_at = Column(DateTime, nullable=False, default=datetime.now)

    soil_moisture = Column(Float, nullable=True)
    temperature = Column(Float, nullable=True)
    humidity = Column(Float, nullable=True)
    raining = Column(Boolean, nullable=True)
    light_level = Column(Float, nullable=True)

    days_since_sowing = Column(Integer, nullable=False)
    previous_moisture_state = Column(String(16), nullable=True)
    moisture_state = Column(String(16), nullable=True)
    alert_codes_json = Column(Text, nullable=False, default="[]")  # current_alert_codes at ingestion time


class DeviceAlertState(Base):
    """Current cooldown/active state per (device, code) -- the cheap hot-path table."""
    __tablename__ = "device_alert_state"

    device_id = Column(String(64), ForeignKey("devices.device_id", ondelete="CASCADE"), primary_key=True)
    code = Column(String(64), primary_key=True)
    is_active = Column(Boolean, nullable=False, default=True)
    last_notified_at = Column(DateTime, nullable=True)


class AlertEvent(Base):
    """Append-only audit row: inserted only when get_new_alerts() decides something is new."""
    __tablename__ = "alert_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(64), ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False, index=True)
    reading_id = Column(Integer, ForeignKey("readings.id", ondelete="CASCADE"), nullable=False)
    alert_code = Column(String(64), nullable=False)
    severity = Column(String(16), nullable=False, default="warning")
    detected_at = Column(DateTime, nullable=False, default=datetime.now)
    fingerprint = Column(String(160), nullable=False, index=True)  # device_id + ":" + alert_code
    active = Column(Boolean, nullable=False, default=True)
    acknowledged = Column(Boolean, nullable=False, default=False)
    resolved_at = Column(DateTime, nullable=True)
    demo_generated = Column(Boolean, nullable=False, default=False)


class DeliveryJob(Base):
    __tablename__ = "delivery_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(64), ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False, index=True)
    reading_id = Column(Integer, ForeignKey("readings.id", ondelete="CASCADE"), nullable=False)
    # JSON list of alert_events.id this job is delivering (consolidated: usually >1).
    alert_event_ids_json = Column(Text, nullable=False, default="[]")
    new_alert_codes_json = Column(Text, nullable=False, default="[]")  # codes that triggered this job

    channel = Column(String(16), nullable=False)  # "sms" or "voice"
    recipient = Column(String(32), nullable=True)
    language = Column(String(8), nullable=False, default="en")
    message_hash = Column(String(64), nullable=True)

    status = Column(String(16), nullable=False, default="pending", index=True)
    # pending -> in_progress -> sent | retrying (-> in_progress again) | failed_permanent
    scheduled_at = Column(DateTime, nullable=False, default=datetime.now)
    next_attempt_at = Column(DateTime, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    provider_message_id = Column(String(128), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.now)
    delivered_at = Column(DateTime, nullable=True)

    test_mode = Column(Boolean, nullable=False, default=False)  # demo-triggered, marked [TEST] in the message
    problem_title = Column(String(200), nullable=True)


class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    delivery_job_id = Column(Integer, ForeignKey("delivery_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_number = Column(Integer, nullable=False)
    attempted_at = Column(DateTime, nullable=False, default=datetime.now)
    success = Column(Boolean, nullable=False)
    status_code = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    retryable = Column(Boolean, nullable=True)
    message = Column(Text, nullable=True)  # the exact text sent (or attempted) -- for the dashboard SMS banner/audit


class SystemEvent(Base):
    __tablename__ = "system_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, nullable=False, default=datetime.now)
    event_type = Column(String(64), nullable=False)
    message = Column(Text, nullable=False)
    device_id = Column(String(64), nullable=True)
    reading_id = Column(Integer, nullable=True)
    alert_event_id = Column(Integer, nullable=True)
    delivery_job_id = Column(Integer, nullable=True)
    meta_json = Column(Text, nullable=True)
