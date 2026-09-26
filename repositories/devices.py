"""
Device lookup, auto-registration, and the sequence-based dedup heuristic
ported 1:1 from the old in-memory state_manager.is_duplicate_sequence.
"""
import hashlib
import hmac
import json
import threading
from datetime import datetime

from db_models import Device

# Guards the whole "dedupe-check through commit" section of /sensor-data
# ingestion (see main.py). A per-request DB session only sees committed data
# from other connections, so a bare Python lock around just the read+mutate
# step is not enough to stop two concurrent requests for the same
# device+sequence both seeing "not a duplicate" -- the lock must be held
# until the deciding transaction actually commits.
INGEST_LOCK = threading.RLock()

# The ESP32 keeps its sequence counter in RAM, so after a power cycle it starts
# again from 0. A sequence that is "not newer" is normally a retry/duplicate, but
# a sequence of 0 (after readings were already seen) or one far below the last
# seen value means the device restarted -- treating it as a duplicate would
# silence the device until its counter caught back up with the old value.
REBOOT_SEQUENCE_DROP = 10


def get(db, device_id: str):
    return db.get(Device, device_id)


def get_or_create(db, device_id: str) -> Device:
    device = db.get(Device, device_id)
    if device is None:
        device = Device(device_id=device_id, first_seen=datetime.now(), last_sequence=-1, status="unknown")
        db.add(device)
        db.flush()
    return device


def _is_restart(last_sequence: int, sequence: int) -> bool:
    return (sequence == 0 and last_sequence > 0) or (last_sequence - sequence > REBOOT_SEQUENCE_DROP)


def is_duplicate_sequence(last_sequence: int, sequence: int) -> bool:
    """A boot_id-less device (all current firmware) is deduped by this heuristic alone."""
    if sequence > last_sequence:
        return False
    return not _is_restart(last_sequence, sequence)


def verify_secret(device: Device, supplied_key: str) -> bool:
    """
    True if this device has no per-device secret provisioned yet (dev-mode
    fallback -- callers only reach here after the global EXPECTED_DEVICE_KEY
    check already passed), or if the supplied key matches its provisioned one.
    """
    if not device.secret_hash:
        return True
    supplied_hash = hashlib.sha256(f"{device.device_id}:{supplied_key}".encode("utf-8")).hexdigest()
    return hmac.compare_digest(supplied_hash, device.secret_hash)


def accept_sequence(db, device_id: str, sequence: int, boot_id: str = None):
    """
    Must be called with INGEST_LOCK held by the caller, for the reason
    explained on INGEST_LOCK above. Returns (accepted: bool, device: Device).
    """
    device = get_or_create(db, device_id)
    if is_duplicate_sequence(device.last_sequence, sequence):
        return False, device
    touch_seen(db, device, sequence=sequence, boot_id=boot_id)
    return True, device


def touch_seen(db, device: Device, *, sequence: int, boot_id: str = None, now: datetime = None):
    device.last_seen = now or datetime.now()
    device.last_sequence = sequence
    if boot_id:
        device.last_boot_id = boot_id
    if device.status in (None, "unknown", "offline"):
        device.status = "online"


def save_reading_snapshot(db, device: Device, *, facts: dict, alert_codes: list, moisture_state: str, updated_at: datetime = None):
    device.last_reading_at = updated_at or datetime.now()
    device.last_facts_json = json.dumps(facts)
    device.last_alert_codes_json = json.dumps(alert_codes)
    device.moisture_state = moisture_state


def update_facts_if_current(db, device: Device, reading, facts: dict, alert_codes: list):
    """
    Replaces the device's snapshot facts with a richer, context-enriched
    version (weather/mandi/recent-rainfall included) computed later by
    services.delivery_queue.process_job(). Guarded by reading timestamp so a
    slow/retried job processed after a NEWER reading already arrived can't
    clobber the dashboard with stale facts -- last_reading_at itself is left
    untouched either way (processing a delivery job is not a new reading).
    """
    if device.last_reading_at is not None and reading.received_at < device.last_reading_at:
        return
    device.last_facts_json = json.dumps(facts)
    device.last_alert_codes_json = json.dumps(alert_codes)


def save_delivery_snapshot(db, device: Device, delivery: dict, delivered_at: datetime = None):
    device.last_delivery_json = json.dumps(delivery)
    device.last_delivery_at = delivered_at or datetime.now()


def snapshot_dict(device: Device) -> dict:
    if device is None or device.last_reading_at is None:
        return None
    snap = {
        "facts": json.loads(device.last_facts_json) if device.last_facts_json else {},
        "alert_codes": json.loads(device.last_alert_codes_json) if device.last_alert_codes_json else [],
        "updated_at": device.last_reading_at.isoformat(),
    }
    if device.last_delivery_json:
        delivery = json.loads(device.last_delivery_json)
        delivery.pop("_reading_id", None)  # internal bookkeeping only -- see save_delivery_snapshot callers
        snap["delivery"] = delivery
        snap["delivery_at"] = device.last_delivery_at.isoformat() if device.last_delivery_at else None
    return snap


def dashboard_device_ids(db) -> list:
    """Devices that have actually produced a reading (i.e. have a snapshot to show)."""
    rows = db.query(Device.device_id).filter(Device.last_reading_at.isnot(None)).all()
    return [r[0] for r in rows]


def all_device_ids(db) -> list:
    return [r[0] for r in db.query(Device.device_id).all()]


def last_updated_map(db) -> dict:
    """One query, for picking the dashboard's default device without an N+1 get_snapshot() loop."""
    rows = (
        db.query(Device.device_id, Device.last_reading_at)
        .filter(Device.last_reading_at.isnot(None))
        .all()
    )
    return {device_id: last_reading_at.isoformat() for device_id, last_reading_at in rows}


def delete_device(db, device_id: str):
    """Cascades to readings/alert state/alert events/delivery jobs/attempts via ON DELETE CASCADE."""
    db.query(Device).filter(Device.device_id == device_id).delete()


def delete_devices_with_prefix(db, prefix: str):
    ids = [d for d in all_device_ids(db) if d.startswith(prefix)]
    for device_id in ids:
        delete_device(db, device_id)
    return ids
