"""Append-only SystemEvent log: config changes, demo actions, provider failures,
backend errors, auth failures, offline events, retry give-ups. Never logs secrets."""
import json
from datetime import datetime

from db_models import SystemEvent


def log(
    db, event_type: str, message: str, *, device_id: str = None, reading_id: int = None,
    alert_event_id: int = None, delivery_job_id: int = None, meta: dict = None,
) -> SystemEvent:
    row = SystemEvent(
        ts=datetime.now(),
        event_type=event_type,
        message=message,
        device_id=device_id,
        reading_id=reading_id,
        alert_event_id=alert_event_id,
        delivery_job_id=delivery_job_id,
        meta_json=json.dumps(meta) if meta else None,
    )
    db.add(row)
    return row
