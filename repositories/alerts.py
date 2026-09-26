"""
Cooldown/new-alert decision, ported 1:1 from the old in-memory
state_manager.get_new_alerts -- just backed by DeviceAlertState instead of a
dict. AlertEvent is the separate, append-only audit trail (see db_models.py).

ACTIONABLE_CODES are the ones gated by state-change + cooldown (they cause a
delivery job only when new or the cooldown has expired). Everything else is
informational and only appears in the message body of an alert that IS being
sent -- it never triggers a delivery by itself.
"""
from datetime import datetime, timedelta

from db_models import AlertEvent, DeviceAlertState

ACTIONABLE_CODES = {
    "LOW_MOISTURE",
    "EXCESS_MOISTURE",
    "FERTILIZER_DUE_BASAL",
    "FERTILIZER_DUE_TILLERING",
    "FERTILIZER_DUE_PANICLE",
    "HARVEST_CHECK_DUE",
    "HARVEST_APPROACHING",
    "RAIN_WARNING",
    "SENSOR_FAULT_DHT22",
    "SENSOR_FAULT_SOIL",
}

# Calendar-driven reminders stay true for days, so they repeat on the long
# calendar cooldown instead of the short live-sensor cooldown.
TIME_BASED_CODES = {
    "FERTILIZER_DUE_BASAL",
    "FERTILIZER_DUE_TILLERING",
    "FERTILIZER_DUE_PANICLE",
    "HARVEST_APPROACHING",
    "HARVEST_CHECK_DUE",
}

SEVERITY_MAP = {
    "SENSOR_FAULT_DHT22": "critical",
    "SENSOR_FAULT_SOIL": "critical",
    "LOW_MOISTURE": "warning",
    "EXCESS_MOISTURE": "warning",
    "RAIN_WARNING": "warning",
    "FERTILIZER_DUE_BASAL": "info",
    "FERTILIZER_DUE_TILLERING": "info",
    "FERTILIZER_DUE_PANICLE": "info",
    "HARVEST_APPROACHING": "info",
    "HARVEST_CHECK_DUE": "info",
}


def fingerprint(device_id: str, code: str) -> str:
    return f"{device_id}:{code}"


def get_new_alerts(
    db, device_id: str, current_codes: list, *,
    alert_cooldown_minutes: float, time_based_cooldown_minutes: float, now: datetime = None,
) -> list:
    """
    Compares current_codes against DeviceAlertState (active + cooldown timers).
    Returns only the codes that should ACTUALLY trigger a new delivery right
    now, and updates DeviceAlertState to reflect this call -- exactly the old
    in-memory get_new_alerts, just DB-backed.
    """
    now = now or datetime.now()
    live_cooldown = timedelta(minutes=alert_cooldown_minutes)
    calendar_cooldown = timedelta(minutes=time_based_cooldown_minutes)

    current_actionable = set(c for c in current_codes if c in ACTIONABLE_CODES)
    existing = {
        row.code: row
        for row in db.query(DeviceAlertState).filter(DeviceAlertState.device_id == device_id).all()
    }

    new_codes = []
    for code in current_actionable:
        cooldown = calendar_cooldown if code in TIME_BASED_CODES else live_cooldown
        row = existing.get(code)
        was_active = bool(row and row.is_active)
        last_sent = row.last_notified_at if row else None
        cooldown_expired = (last_sent is None) or (now - last_sent >= cooldown)

        if (not was_active) or cooldown_expired:
            new_codes.append(code)
            if row is None:
                row = DeviceAlertState(device_id=device_id, code=code, is_active=True, last_notified_at=now)
                db.add(row)
            else:
                row.is_active = True
                row.last_notified_at = now
        elif row is not None:
            row.is_active = True

    # A code that WAS active but no longer is just gets dropped silently (e.g.
    # moisture went from low back to normal) -- no "all clear" notification.
    for code, row in existing.items():
        if row.is_active and code not in current_actionable:
            row.is_active = False

    return sorted(new_codes)


def set_last_notified_at(db, device_id: str, code: str, when: datetime):
    """Test-only helper: lets a test fast-forward a specific alert's cooldown clock."""
    row = db.query(DeviceAlertState).filter_by(device_id=device_id, code=code).one_or_none()
    if row is not None:
        row.last_notified_at = when


def create_alert_events(db, device_id: str, reading_id: int, new_codes: list, *, demo_generated: bool = False, now: datetime = None) -> list:
    now = now or datetime.now()
    events = []
    for code in new_codes:
        event = AlertEvent(
            device_id=device_id,
            reading_id=reading_id,
            alert_code=code,
            severity=SEVERITY_MAP.get(code, "warning"),
            detected_at=now,
            fingerprint=fingerprint(device_id, code),
            active=True,
            demo_generated=demo_generated,
        )
        db.add(event)
        events.append(event)
    db.flush()  # populate event.id for the delivery job's alert_event_ids
    return events
