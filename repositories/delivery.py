"""
DeliveryJob/DeliveryAttempt CRUD, the atomic job-claim query, and backoff
scheduling. See services/delivery_queue.py for the actual send/retry logic
that uses these.
"""
import json
from datetime import datetime, timedelta

from sqlalchemy import update

from db_models import DeliveryAttempt, DeliveryJob


def create_job(
    db, *, device_id, reading_id, alert_event_ids, new_alert_codes, channel, recipient,
    language: str = "en", scheduled_at: datetime = None, test_mode: bool = False, problem_title: str = None,
) -> DeliveryJob:
    job = DeliveryJob(
        device_id=device_id,
        reading_id=reading_id,
        alert_event_ids_json=json.dumps(alert_event_ids),
        new_alert_codes_json=json.dumps(new_alert_codes),
        channel=channel,
        recipient=recipient,
        language=language,
        status="pending",
        scheduled_at=scheduled_at or datetime.now(),
        created_at=datetime.now(),
        attempts=0,
        test_mode=test_mode,
        problem_title=problem_title,
    )
    db.add(job)
    db.flush()
    return job


def get(db, job_id: int) -> DeliveryJob:
    return db.get(DeliveryJob, job_id)


def due_pending_jobs(db, *, now: datetime = None, limit: int = 50):
    now = now or datetime.now()
    return (
        db.query(DeliveryJob)
        .filter(DeliveryJob.status.in_(["pending", "retrying"]))
        .filter(DeliveryJob.scheduled_at <= now)
        .filter((DeliveryJob.next_attempt_at.is_(None)) | (DeliveryJob.next_attempt_at <= now))
        .order_by(DeliveryJob.scheduled_at.asc())
        .limit(limit)
        .all()
    )


def claim_job(db, job_id: int) -> bool:
    """
    Atomic pending/retrying -> in_progress flip, committed immediately. Returns
    True only for the caller that actually won the claim. Required because both
    a demo endpoint's synchronous call and the background poller can reach the
    same job.
    """
    result = db.execute(
        update(DeliveryJob)
        .where(DeliveryJob.id == job_id, DeliveryJob.status.in_(["pending", "retrying"]))
        .values(status="in_progress")
    )
    db.commit()
    return result.rowcount == 1


def record_attempt(
    db, job: DeliveryJob, *, success: bool, status_code: int = None, error: str = None,
    retryable: bool = None, provider_message_id: str = None, message: str = None,
) -> DeliveryAttempt:
    job.attempts += 1
    attempt = DeliveryAttempt(
        delivery_job_id=job.id,
        attempt_number=job.attempts,
        attempted_at=datetime.now(),
        success=success,
        status_code=status_code,
        error=error,
        retryable=retryable,
        message=message,
    )
    db.add(attempt)
    if provider_message_id:
        job.provider_message_id = provider_message_id
    return attempt


def mark_sent(db, job: DeliveryJob):
    job.status = "sent"
    job.delivered_at = datetime.now()
    job.next_attempt_at = None
    job.last_error = None


def mark_retrying(db, job: DeliveryJob, *, backoff_seconds: int, error: str):
    job.status = "retrying"
    job.last_error = error
    job.next_attempt_at = datetime.now() + timedelta(seconds=backoff_seconds)


def mark_failed_permanent(db, job: DeliveryJob, *, error: str):
    job.status = "failed_permanent"
    job.last_error = error
    job.next_attempt_at = None


def recent_sms_attempts(db, device_id: str, limit: int = 10) -> list:
    return (
        db.query(DeliveryAttempt)
        .join(DeliveryJob, DeliveryAttempt.delivery_job_id == DeliveryJob.id)
        .filter(DeliveryJob.device_id == device_id, DeliveryJob.channel == "sms")
        .order_by(DeliveryAttempt.attempted_at.desc())
        .limit(limit)
        .all()
    )
