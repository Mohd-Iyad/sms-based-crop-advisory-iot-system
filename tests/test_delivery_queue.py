"""
Tests for the outbox itself (services/delivery_queue.py + repositories/delivery.py):
retry/backoff progression, the atomic job-claim race, and persistence across
what a real process restart would look like (a fresh connection to the same
database file). Regression coverage for rollback-on-failure and crash
recovery lives in tests/test_regressions.py, next to the rest of the pinned
bugs; this file is about the outbox mechanics on their own.
"""
import os
import sys
import threading
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import database
import main
import state_manager
import services.delivery_queue as delivery_queue
from db_models import DeliveryJob

KEY = {"X-Device-Key": "test-key"}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    client.cookies.clear()
    monkeypatch.setattr(main, "EXPECTED_DEVICE_KEY", "test-key")
    monkeypatch.setattr(main, "SOWING_DATE", (date.today() - timedelta(days=5)).isoformat())
    monkeypatch.setattr(delivery_queue, "ENABLE_VOICE_CALL", False)
    monkeypatch.setattr(state_manager, "ALERT_COOLDOWN_MINUTES", 720)
    monkeypatch.setattr(delivery_queue, "get_weather", lambda: {"available": True, "rain_expected": False, "forecast": []})
    monkeypatch.setattr(delivery_queue, "get_mandi_price", lambda: {"available": False})
    sms = []
    monkeypatch.setattr(delivery_queue, "send_sms", lambda m, **_: (sms.append(m), {"success": True, "status_code": 201})[1])
    yield sms


client = TestClient(main.app)


def reading(seq, moisture=20.0, device="D1", **kw):
    body = {"device_id": device, "sequence": seq, "soil_moisture": moisture,
            "temperature": 28.0, "humidity": 60.0, "raining": False}
    body.update(kw)
    return body


def post(seq, moisture=20.0, **kw):
    return client.post("/sensor-data", json=reading(seq, moisture, **kw), headers=KEY)


# ------------------------------------------------------------- backoff progression

def test_backoff_follows_the_configured_fixed_sequence(monkeypatch, env):
    """
    next_attempt_at is always scheduled from the REAL wall clock at the moment
    an attempt is made (not from the simulated `now` used only to decide
    whether a job is currently due) -- a real backoff timer must be real time.
    """
    monkeypatch.setattr(delivery_queue, "send_sms", lambda m, **_: {"success": False, "error": "down", "retryable": True})
    post(1)

    before = datetime.now()
    delivery_queue.process_all_pending()             # attempt 1 -> retrying, next due in ~30s
    job = _the_only_job()
    assert job.attempts == 1 and job.status == "retrying"
    assert 25 <= (job.next_attempt_at - before).total_seconds() <= 35

    assert delivery_queue.process_all_pending(now=datetime.now() + timedelta(seconds=10)) == []   # not due yet

    before = datetime.now()
    delivery_queue.process_all_pending(now=before + timedelta(seconds=31))   # attempt 2 -> next due in ~60s
    job = _the_only_job()
    assert job.attempts == 2
    assert 55 <= (job.next_attempt_at - before).total_seconds() <= 65


def test_backoff_caps_at_the_last_configured_value(monkeypatch, env):
    monkeypatch.setattr(delivery_queue, "SMS_RETRY_BACKOFF_SECONDS", [10, 20])
    monkeypatch.setattr(delivery_queue, "SMS_RETRY_MAX_ATTEMPTS", 5)
    monkeypatch.setattr(delivery_queue, "send_sms", lambda m, **_: {"success": False, "error": "down", "retryable": True})
    post(1)
    due_at = datetime.now()
    before = due_at
    for _ in range(4):
        before = datetime.now()
        delivery_queue.process_all_pending(now=due_at)
        due_at = due_at + timedelta(seconds=25)
    job = _the_only_job()
    assert job.attempts == 4
    # attempt 4 (the 3rd retry) uses the LAST configured backoff (20s), not something larger
    assert 15 <= (job.next_attempt_at - before).total_seconds() <= 25


def _the_only_job() -> DeliveryJob:
    with database.session_scope() as db:
        jobs = db.query(DeliveryJob).all()
        assert len(jobs) == 1
        db.expunge(jobs[0])
        return jobs[0]


# ------------------------------------------------------------- atomic claim

def test_concurrent_processing_of_the_same_job_only_delivers_once(env):
    """
    Simulates the race the atomic claim_job() UPDATE exists for: the demo
    endpoint's synchronous call and the background worker's poll could both
    reach process_job() for the same row at nearly the same instant.
    """
    post(1)
    with database.session_scope() as db:
        job_id = db.query(DeliveryJob).one().id

    results = []

    def go():
        with database.session_scope() as db:
            results.append(delivery_queue.process_job(db, job_id))

    threads = [threading.Thread(target=go) for _ in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    successful = [r for r in results if r is not None]
    assert len(successful) == 1
    assert len(env) == 1


# ------------------------------------------------------------- persistence across a restart

def test_pending_jobs_survive_what_a_process_restart_would_look_like(env):
    """
    DATABASE_URL points at a real file (tests/conftest.py); this attaches with
    a BRAND NEW engine/session -- no cached objects, no shared connection pool
    with the app's own `database.engine` -- to prove the job is durable on
    disk, not just visible because it's the same Python process.
    """
    post(1)
    with database.session_scope() as db:
        job_id = db.query(DeliveryJob).one().id
        assert db.get(DeliveryJob, job_id).status == "pending"

    fresh_engine = create_engine(config.DATABASE_URL, connect_args={"check_same_thread": False})
    FreshSession = sessionmaker(bind=fresh_engine, future=True)
    fresh_db = FreshSession()
    try:
        job = fresh_db.get(DeliveryJob, job_id)
        assert job is not None and job.status == "pending"
    finally:
        fresh_db.close()
        fresh_engine.dispose()

    # and it's still processable through the normal path afterwards
    delivery_queue.process_all_pending()
    assert len(env) == 1


# ------------------------------------------------------------- idempotency

def test_duplicate_reading_never_creates_a_second_job(env):
    first = post(1, 20).json()
    dup = post(1, 20).json()
    assert first["delivery_jobs_created"] and dup["duplicate"] is True and dup["delivery_jobs_created"] == []
    with database.session_scope() as db:
        assert db.query(DeliveryJob).count() == len(first["delivery_jobs_created"])


def test_two_devices_processed_independently_in_parallel(env):
    results = {"A": [], "B": []}

    def go(device):
        for seq in range(3):
            results[device].append(client.post("/sensor-data", json=reading(seq, 20, device=device), headers=KEY).json())

    threads = [threading.Thread(target=go, args=(d,)) for d in ("A", "B")]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert all(not r.get("duplicate") for r in results["A"])
    assert all(not r.get("duplicate") for r in results["B"])
    delivery_queue.process_all_pending()
    assert len(env) == 2   # one alert per device (cooldown suppresses the other two readings each)
