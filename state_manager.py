"""
DB-backed shim over the repositories, kept as its own module (and with its
original function names/signatures where dashboard.py or a test uses them
directly) so this stayed exactly what its own earlier docstring promised: "the
architecture already separates this into its own module... so swapping it out
later is a one-file change." That swap is this file.

What's NOT preserved from the old in-memory version: get_device_state()'s
reference-mutation contract (a test writing into a returned dict in place) --
that only worked because the old store was a plain Python dict, and cannot be
honored by a DB-backed shim without becoming a fake in-memory cache again.
reset_all_state_for_tests() replaces the old direct `_STATE_STORE.clear()`
access used by test fixtures.

The real ingestion write path (accept_sequence + get_new_alerts + persisting
Reading/AlertEvent/DeliveryJob rows in ONE atomic transaction) lives directly
in main.py against repositories/*, NOT through this module -- routing it
through here would mean opening a second, separately-committed DB session for
the dedupe decision, which would break the atomicity that makes "no false
cooldown on a mid-request crash" free (see repositories/devices.INGEST_LOCK
and main.py for why). This module is the read-mostly shim the DASHBOARD and a
couple of direct-call regression tests need, plus small process-wide runtime
settings (SMS language) that were never per-device state to begin with.
"""
from datetime import datetime

from config import ALERT_COOLDOWN_MINUTES, TIME_BASED_ALERT_COOLDOWN_MINUTES, TRANSLATE_SMS_TO
from database import session_scope
from db_models import Base, DeliveryAttempt, DeliveryJob, Reading
import sms_i18n

import repositories.alerts as alerts_repo
import repositories.delivery as delivery_repo
import repositories.devices as devices_repo
import repositories.readings as readings_repo

ACTIONABLE_CODES = alerts_repo.ACTIONABLE_CODES
TIME_BASED_CODES = alerts_repo.TIME_BASED_CODES

# Process-wide (not per-device), same in-memory lifetime as before: an
# operator's dashboard language choice. Deliberately NOT persisted to the DB
# in this phase -- it's a cosmetic default, not alert/delivery state, and the
# full dashboard-settings persistence story is a later phase (see the plan).
_SMS_LANGUAGE = None

# Set once, at process import time (before the TZ pin in config.py could ever
# be bypassed -- config is imported above, transitively, before this runs),
# so the dashboard can show how long this backend process has been running.
_SERVER_START_TIME = datetime.now()


def get_server_start_time() -> datetime:
    return _SERVER_START_TIME


def get_uptime_seconds() -> float:
    return (datetime.now() - _SERVER_START_TIME).total_seconds()


def get_sms_language() -> str:
    """Language for every SMS: the dashboard choice if one was made, else TRANSLATE_SMS_TO, else English."""
    return _SMS_LANGUAGE or sms_i18n.normalize_language(TRANSLATE_SMS_TO)


def set_sms_language(lang: str):
    global _SMS_LANGUAGE
    _SMS_LANGUAGE = sms_i18n.normalize_language(lang)


def reset_runtime():
    """Forgets the dashboard language choice (used by tests)."""
    global _SMS_LANGUAGE
    _SMS_LANGUAGE = None


def get_new_alerts(device_id: str, current_codes: list) -> list:
    """Thin wrapper so tests that exercised cooldown timing directly still can."""
    with session_scope() as db:
        devices_repo.get_or_create(db, device_id)  # DeviceAlertState has a FK to devices
        result = alerts_repo.get_new_alerts(
            db, device_id, current_codes,
            alert_cooldown_minutes=ALERT_COOLDOWN_MINUTES,
            time_based_cooldown_minutes=TIME_BASED_ALERT_COOLDOWN_MINUTES,
        )
        db.commit()
        return result


def set_last_notified_at(device_id: str, code: str, when: datetime):
    """Test-only: fast-forwards one alert's cooldown clock (replaces the old direct last_sent[code] -= ... access)."""
    with session_scope() as db:
        alerts_repo.set_last_notified_at(db, device_id, code, when)
        db.commit()


def set_test_snapshot(device_id: str, *, facts: dict, alert_codes: list, delivery: dict = None):
    """
    Test-only: writes a snapshot directly, bypassing the normal reading
    pipeline. Replaces the old state_manager.save_snapshot() / direct
    get_device_state(...)["last_snapshot"] = ... access, which relied on the
    in-memory dict's reference-mutation semantics this DB-backed shim doesn't have.
    """
    with session_scope() as db:
        device = devices_repo.get_or_create(db, device_id)
        devices_repo.save_reading_snapshot(db, device, facts=facts, alert_codes=alert_codes, moisture_state=None)
        if delivery is not None:
            devices_repo.save_delivery_snapshot(db, device, delivery)
        db.commit()


def get_snapshot(device_id: str):
    with session_scope() as db:
        return devices_repo.snapshot_dict(devices_repo.get(db, device_id))


def get_dashboard_device_ids() -> list:
    with session_scope() as db:
        return devices_repo.dashboard_device_ids(db)


def get_all_device_ids() -> list:
    with session_scope() as db:
        return devices_repo.all_device_ids(db)


def get_last_updated_map() -> dict:
    """One query: device_id -> last_reading_at (iso), used to pick the dashboard's default device without an N+1 loop."""
    with session_scope() as db:
        return devices_repo.last_updated_map(db)


def get_last_sms_event():
    """
    The most recent SMS delivery ATTEMPT (any device), for the dashboard
    banner -- derived from DeliveryAttempt/DeliveryJob, so unlike the old
    in-memory version this survives a backend restart.
    """
    with session_scope() as db:
        attempt = (
            db.query(DeliveryAttempt)
            .join(DeliveryJob, DeliveryAttempt.delivery_job_id == DeliveryJob.id)
            .filter(DeliveryJob.channel == "sms")
            .order_by(DeliveryAttempt.attempted_at.desc())
            .first()
        )
        if attempt is None:
            return None
        job = db.get(DeliveryJob, attempt.delivery_job_id)
        reading = db.get(Reading, job.reading_id) if job else None
        return {
            "device_id": job.device_id if job else None,
            "language": job.language if job else "en",
            "ok": bool(attempt.success),
            "error": attempt.error,
            "message": attempt.message,
            "reading_at": reading.received_at.isoformat() if reading else None,
            "sent_at": attempt.attempted_at.isoformat(),
            "simulated": bool(job.test_mode) if job else False,
            "problem": job.problem_title if job else None,
        }


def get_recent_readings(device_id: str, limit: int = 10) -> list:
    """Most recent readings for one device, newest first -- for the dashboard's activity log."""
    with session_scope() as db:
        return [
            {
                "received_at": r.received_at, "soil_moisture": r.soil_moisture,
                "temperature": r.temperature, "humidity": r.humidity, "raining": r.raining,
            }
            for r in readings_repo.recent(db, device_id, limit)
        ]


def get_recent_sms_events(device_id: str, limit: int = 10) -> list:
    """Most recent SMS delivery attempts for one device, newest first -- for the dashboard's activity log."""
    with session_scope() as db:
        return [
            {"attempted_at": a.attempted_at, "success": bool(a.success), "error": a.error}
            for a in delivery_repo.recent_sms_attempts(db, device_id, limit)
        ]


def reset_device(device_id: str):
    """Forgets everything about one device (used to make /demo/trigger and /demo/scenario/* repeatable)."""
    with session_scope() as db:
        devices_repo.delete_device(db, device_id)
        db.commit()


def clear_simulation():
    """"Back to real values": forgets every simulated (DEMO*) device. Real devices are untouched."""
    with session_scope() as db:
        devices_repo.delete_devices_with_prefix(db, "DEMO")
        db.commit()


def reset_all_state_for_tests():
    """Truncates every table. Replaces the old direct `_STATE_STORE.clear()` access in test fixtures."""
    with session_scope() as db:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
    reset_runtime()
