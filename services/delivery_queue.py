"""
The outbox: creates DeliveryJob rows at ingestion time (cheap, synchronous,
no I/O) and processes them later -- either from the background worker thread
(services/worker.py, real ESP32 traffic) or inline, once, right after creation
(main.py's demo/trigger endpoints, for instant investor-demo feedback).

Nothing in here is called from the /sensor-data request path directly.

Names are imported here (not looked up via config.* at call time) so tests can
monkeypatch services.delivery_queue.send_sms / .get_weather / .get_mandi_price /
etc. -- the same "patch where it's used" convention main.py used to rely on,
just moved to where delivery now actually happens.
"""
import json
import logging
from datetime import datetime

from config import (
    ADVISORY_RECIPIENTS, ENABLE_VOICE_CALL, SMS_RETRY_BACKOFF_SECONDS, SMS_RETRY_MAX_ATTEMPTS,
)
from database import session_scope
from mandi import get_mandi_price
from message_planner import build_sms_message, build_voice_message
from rule_engine import evaluate
from telephony import make_voice_call, send_sms
from weather import get_recent_rainfall, get_weather

import repositories.delivery as delivery_repo
import repositories.devices as devices_repo
import repositories.events as events_repo
import repositories.readings as readings_repo

log = logging.getLogger("delivery_queue")


def create_delivery_jobs_for_reading(
    db, device, reading, alert_events: list, new_codes: list, *,
    language: str = "en", test_mode: bool = False, problem_title: str = None,
) -> list:
    """
    One SMS job (and one voice job too, if ENABLE_VOICE_CALL) per RECIPIENT,
    per reading that produced new alerts -- v5 fans this out across every
    number in ADVISORY_RECIPIENTS (a household often has more than one phone
    that should hear about the field), each with its own independent
    retry/backoff so one bad number never blocks or delays the others. Also
    seeds the device's delivery snapshot so the dashboard shows
    "pending"/"disabled (SMS-only mode)" immediately, instead of nothing,
    before the worker has had a chance to run.
    """
    if not alert_events or not ADVISORY_RECIPIENTS:
        return []

    alert_event_ids = [e.id for e in alert_events]
    jobs = []
    for recipient in ADVISORY_RECIPIENTS:
        jobs.append(delivery_repo.create_job(
            db, device_id=device.device_id, reading_id=reading.id, alert_event_ids=alert_event_ids,
            new_alert_codes=new_codes, channel="sms", recipient=recipient, language=language,
            test_mode=test_mode, problem_title=problem_title,
        ))
        if ENABLE_VOICE_CALL:
            jobs.append(delivery_repo.create_job(
                db, device_id=device.device_id, reading_id=reading.id, alert_event_ids=alert_event_ids,
                new_alert_codes=new_codes, channel="voice", recipient=recipient, language=language,
                test_mode=test_mode, problem_title=problem_title,
            ))

    devices_repo.save_delivery_snapshot(db, device, {
        "_reading_id": reading.id,
        "sms_status": "pending",
        "voice_status": "pending" if ENABLE_VOICE_CALL else "disabled (SMS-only mode)",
    })
    # Not committed here -- the caller (main.py) owns the transaction boundary,
    # so "persist reading + alert state + these jobs" stays one atomic unit.
    # (A later process_job() call in the same session commits it implicitly,
    # via its own claim_job() UPDATE+commit, for the synchronous demo path.)
    return jobs


def _update_device_delivery_snapshot(db, device, job, status_text: str):
    current = json.loads(device.last_delivery_json) if device.last_delivery_json else {}
    if current.get("_reading_id") != job.reading_id:
        current = {"_reading_id": job.reading_id}
    current["sms_status" if job.channel == "sms" else "voice_status"] = status_text
    devices_repo.save_delivery_snapshot(db, device, current)


def process_job(db, job_id: int) -> dict:
    """
    Claims, attempts, and records the outcome of ONE delivery job. Returns
    None if another caller (the worker, or a concurrent demo call) already
    claimed it first -- callers should treat that as "not my job to report on".

    This is the ONLY place weather/mandi/SMS/voice are called for a real
    alert -- never from the /sensor-data request path.
    """
    if not delivery_repo.claim_job(db, job_id):
        return None

    try:
        return _process_claimed_job(db, job_id)
    except Exception as exc:
        db.rollback()
        # claim_job() already committed "in_progress" in its OWN transaction, so
        # this rollback can't undo it -- without the recovery below, any
        # exception here (a template bug, a bad monkeypatch, ...) would strand
        # the job in "in_progress" forever: due_pending_jobs() only ever selects
        # pending/retrying, so it would never be picked up again. Explicitly
        # bounce it back to retrying (or give up, past the attempt cap) instead.
        with session_scope() as recovery_db:
            recovery_job = delivery_repo.get(recovery_db, job_id)
            if recovery_job is not None and recovery_job.status == "in_progress":
                error = f"internal error: {exc}"
                if recovery_job.attempts < SMS_RETRY_MAX_ATTEMPTS:
                    backoff = SMS_RETRY_BACKOFF_SECONDS[min(recovery_job.attempts, len(SMS_RETRY_BACKOFF_SECONDS) - 1)]
                    delivery_repo.mark_retrying(recovery_db, recovery_job, backoff_seconds=backoff, error=error)
                else:
                    delivery_repo.mark_failed_permanent(recovery_db, recovery_job, error=error)
                events_repo.log(
                    recovery_db, "delivery_processing_error", f"job {job_id} raised while processing: {exc}",
                    delivery_job_id=job_id,
                )
            recovery_db.commit()
        raise


def _process_claimed_job(db, job_id: int) -> dict:
    job = delivery_repo.get(db, job_id)
    device = devices_repo.get(db, job.device_id)
    reading = readings_repo.get(db, job.reading_id)
    new_codes = json.loads(job.new_alert_codes_json)

    weather = get_weather()
    mandi = get_mandi_price()
    recent_rainfall = get_recent_rainfall() if "EXCESS_MOISTURE" in new_codes else None

    result = evaluate(
        soil_moisture=reading.soil_moisture,
        temperature=reading.temperature,
        humidity=reading.humidity,
        raining=reading.raining,
        light_level=reading.light_level,
        days_since_sowing=reading.days_since_sowing,
        previous_moisture_state=reading.previous_moisture_state,
        weather=weather,
        mandi=mandi,
        recent_rainfall=recent_rainfall,
    )
    facts = result["facts"]
    alert_codes = result["alert_codes"]
    prefix = "[TEST] " if job.test_mode else ""

    if job.channel == "voice":
        message = build_voice_message(new_codes)
        send_result = make_voice_call(message, to=job.recipient)
    else:
        message = prefix + build_sms_message(alert_codes, facts, lang=job.language, reading_time=reading.received_at)
        send_result = send_sms(message, to=job.recipient)

    # From here on, a real side effect may already have happened (the SMS/call
    # provider was called) -- that can't be rolled back. Record the outcome and
    # commit it IMMEDIATELY, before anything else that could raise: otherwise a
    # later failure (e.g. updating the dashboard snapshot) would roll back this
    # whole transaction, making a genuinely-sent message look never-sent, and
    # the next retry would send it again.
    success = bool(send_result.get("success"))
    retryable = bool(send_result.get("retryable")) if not success else False
    error_text = None if success else str(send_result.get("error", send_result.get("status_code")))

    delivery_repo.record_attempt(
        db, job, success=success, status_code=send_result.get("status_code"),
        error=error_text, retryable=retryable, provider_message_id=send_result.get("provider_message_id"),
        message=message,
    )
    log.info(
        "%s %s: device=%s job=%s attempt=%d recipient=%s%s",
        job.channel.upper(), "sent" if success else "failed", job.device_id, job.id, job.attempts,
        job.recipient, "" if success else f" error={error_text}",
    )

    status_text = "sent" if success else f"failed: {error_text}"

    if success:
        delivery_repo.mark_sent(db, job)
    elif retryable and job.attempts < SMS_RETRY_MAX_ATTEMPTS:
        backoff = SMS_RETRY_BACKOFF_SECONDS[min(job.attempts - 1, len(SMS_RETRY_BACKOFF_SECONDS) - 1)]
        delivery_repo.mark_retrying(db, job, backoff_seconds=backoff, error=status_text)
    else:
        delivery_repo.mark_failed_permanent(db, job, error=status_text)
        events_repo.log(
            db, "delivery_giveup",
            f"{job.channel} delivery gave up after {job.attempts} attempt(s): {status_text}",
            device_id=job.device_id, delivery_job_id=job.id,
        )
    db.commit()  # the delivery outcome is now durable, independent of everything below

    # Best-effort dashboard snapshot update. A failure here must NOT retry the
    # job -- its outcome is already final and already committed above.
    try:
        if device is not None:
            _update_device_delivery_snapshot(db, device, job, status_text)
            devices_repo.update_facts_if_current(db, device, reading, facts, alert_codes)
            db.commit()
    except Exception:
        db.rollback()
        log.exception("job %s: delivery outcome recorded, but the dashboard snapshot update failed", job.id)

    return {
        "job_id": job.id,
        "channel": job.channel,
        "success": success,
        "status": job.status,
        "status_text": status_text,
        "message": message,
        "facts": facts,
        "alert_codes": alert_codes,
    }


def process_all_pending(limit: int = None, now: datetime = None) -> list:
    """
    Processes every currently-due job in one pass, each in its own session
    (never shared across threads). Used by the background worker loop AND
    directly by tests, so "did /sensor-data avoid blocking on delivery" can be
    asserted deterministically (mocked send_sms not called until this runs)
    instead of via wall-clock timing. `now` lets a test simulate time passing
    (e.g. to make a job that's `retrying` with a future next_attempt_at
    become due) without manipulating the database directly.
    """
    with session_scope() as db:
        job_ids = [j.id for j in delivery_repo.due_pending_jobs(db, now=now, limit=limit or 1000)]

    results = []
    for job_id in job_ids:
        with session_scope() as db:
            try:
                result = process_job(db, job_id)
            except Exception:
                db.rollback()
                log.exception("delivery job %s raised while processing", job_id)
                continue
            if result is not None:
                results.append(result)
    return results
