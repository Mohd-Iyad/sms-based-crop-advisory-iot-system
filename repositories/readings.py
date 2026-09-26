"""Persists one sensor reading, with everything services/delivery_queue.py
needs later to reproduce the context-enriched rule evaluation asynchronously."""
import json
from datetime import datetime

from db_models import Reading


def create(
    db, *, device_id, boot_id, sequence, soil_moisture, temperature, humidity, raining,
    light_level, days_since_sowing, previous_moisture_state, moisture_state, alert_codes,
    received_at: datetime = None,
) -> Reading:
    reading = Reading(
        device_id=device_id,
        boot_id=boot_id,
        sequence=sequence,
        received_at=received_at or datetime.now(),
        soil_moisture=soil_moisture,
        temperature=temperature,
        humidity=humidity,
        raining=raining,
        light_level=light_level,
        days_since_sowing=days_since_sowing,
        previous_moisture_state=previous_moisture_state,
        moisture_state=moisture_state,
        alert_codes_json=json.dumps(alert_codes),
    )
    db.add(reading)
    db.flush()
    return reading


def get(db, reading_id: int) -> Reading:
    return db.get(Reading, reading_id)


def recent(db, device_id: str, limit: int = 10) -> list:
    return (
        db.query(Reading)
        .filter(Reading.device_id == device_id)
        .order_by(Reading.received_at.desc())
        .limit(limit)
        .all()
    )
