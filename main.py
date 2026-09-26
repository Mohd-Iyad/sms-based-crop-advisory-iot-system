"""
Main FastAPI app -- v5.

v5 adds multi-recipient delivery (ADVISORY_TO_NUMBERS, see config.py and
services/delivery_queue.py) and a production-realistic default alert cadence
(ALERT_COOLDOWN_MINUTES=360, i.e. every 6 hours instead of every 5 minutes).

Architectural change from v2: /sensor-data no longer waits for weather /
mandi / SMS / voice before answering the ESP32. It authenticates, validates,
dedupes, persists the reading, evaluates the (pure, no-I/O) rule engine, and
creates AlertEvent + DeliveryJob rows -- all in one atomic transaction -- then
returns HTTP 202 immediately. A background worker (services/worker.py) picks
up DeliveryJob rows and does the actual weather/mandi/SMS/voice work, with
persistent retry/backoff (services/delivery_queue.py). Nothing external can
block, delay, or lose a sensor reading anymore.

/demo/trigger and /demo/scenario/{name} still feel instant: they create the
same DeliveryJob rows and then call the SAME process_job() the worker uses,
just synchronously, right there in the request -- so the investor-facing
dashboard redirect still shows delivery status immediately.

/sensor-data-preview is unchanged: it never persists and never delivers, so
it was never subject to the blocking problem this rework fixes.
"""
import hmac
import logging
from datetime import datetime
from typing import Optional

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from models import SensorData
from rule_engine import evaluate, compute_days_since_sowing
from weather import get_weather, get_recent_rainfall
from mandi import get_mandi_price
from message_planner import build_voice_message, build_sms_message
from dashboard import render_dashboard
from database import get_db, init_db
from urllib.parse import quote
import state_manager
import demo_scenarios
import sms_i18n
import re

import repositories.alerts as alerts_repo
import repositories.devices as devices_repo
import repositories.readings as readings_repo
import services.delivery_queue as delivery_queue
import services.worker as worker

from config import (
    ADVISORY_RECIPIENTS, EXPECTED_DEVICE_KEY, SOWING_DATE, ENABLE_VOICE_CALL, TRANSLATE_SMS_TO, PUBLIC_MODE,
    ENABLE_DELIVERY_WORKER,
)

# Wall-clock timestamps on every log line (previously none -- Python's "last resort" handler
# only prints LEVEL:logger:message). asctime defaults to time.localtime, which by this point
# already reflects the Asia/Kolkata pin from config.py (imported transitively above via dashboard).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_WEAK_KEYS = {"demo-key-123", "change-me", "changeme", "test-key", "password", "secret"}


def public_mode_problem(key: str) -> Optional[str]:
    """Why this key is not acceptable for a server on the public internet (None if it is fine)."""
    if not key:
        return "EXPECTED_DEVICE_KEY is empty"
    if len(key) < 16 or key.lower() in _WEAK_KEYS:
        return "EXPECTED_DEVICE_KEY is too short or a well-known placeholder (use 16+ random characters)"
    return None


if PUBLIC_MODE and public_mode_problem(EXPECTED_DEVICE_KEY):
    # Fail closed: anyone who can reach a public server could otherwise send SMS from it.
    raise RuntimeError(
        f"PUBLIC_MODE=true but {public_mode_problem(EXPECTED_DEVICE_KEY)}. Set a strong key in the "
        "environment (and the same value as DEVICE_KEY in the ESP32's config.h), e.g.: "
        'python -c "import secrets; print(secrets.token_urlsafe(24))"'
    )

# On a public server the interactive API docs are switched off (they advertise every endpoint).
app = FastAPI(
    title="Crop Advisory Backend v5",
    **({"docs_url": None, "redoc_url": None, "openapi_url": None} if PUBLIC_MODE else {}),
)

init_db()

if not EXPECTED_DEVICE_KEY:
    logging.warning(
        "EXPECTED_DEVICE_KEY is not set: /sensor-data and /demo/trigger accept requests from "
        "ANYONE, and can send real SMS. Set it in .env (and the same value as DEVICE_KEY in the "
        "ESP32's config.h) before exposing this server to a network."
    )


_bad_recipients = [n for n in ADVISORY_RECIPIENTS if not re.fullmatch(r"\+\d{8,15}", n)]
if not ADVISORY_RECIPIENTS:
    logging.warning(
        "ADVISORY_TO_NUMBER / ADVISORY_TO_NUMBERS is empty: SMS alerts will not reach anyone. "
        "Set it in .env."
    )
elif _bad_recipients:
    logging.warning(
        "These entries in ADVISORY_TO_NUMBERS are not in international format (e.g. "
        "+919876543210) and will be skipped at send time: %s", ", ".join(_bad_recipients),
    )


if TRANSLATE_SMS_TO and not sms_i18n.is_supported(TRANSLATE_SMS_TO):
    logging.warning(
        "TRANSLATE_SMS_TO=%r is not supported (built-in templates exist for: %s). "
        "SMS will be sent in English.", TRANSLATE_SMS_TO, ", ".join(sms_i18n.SUPPORTED_LANGUAGES),
    )


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    """
    A 422 that never echoes the offending input back. FastAPI's default handler
    includes the raw input in the response, and for a value like NaN that cannot
    be serialised to JSON at all -- which turned a bad request into a 500.
    """
    errors = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


# The dashboard remembers the access key in this cookie after it has been entered once, so the
# buttons keep working (and the key never has to sit in the address bar). HttpOnly + SameSite=Strict:
# scripts can't read it and other sites can't make the browser send it with a form post.
_KEY_COOKIE = "advisory_key"
_KEY_COOKIE_MAX_AGE = 12 * 3600


def _check_device_key(x_device_key: str = None, query_key: str = None, cookie_key: str = None):
    """
    Simple shared-secret check. If EXPECTED_DEVICE_KEY is not configured,
    the check is skipped entirely (useful for local testing) -- but for any
    real deployment, set EXPECTED_DEVICE_KEY so random requests can't
    trigger a real phone call.

    Accepts the key via the X-Device-Key header (ESP32, API clients), a
    `key` query parameter, or the dashboard's cookie (plain HTML <form> buttons
    can't set custom headers without JavaScript, and this dashboard deliberately
    stays JS-free -- see dashboard.py).

    A device with its OWN provisioned secret (repositories.devices.secret_hash)
    is checked in the /sensor-data handler itself, once the device row is
    available -- this shared-secret check is the (dev-mode-compatible) floor
    every request must clear first.
    """
    if not EXPECTED_DEVICE_KEY:
        return
    supplied = (x_device_key or query_key or cookie_key or "").encode("utf-8")
    # constant-time comparison, so the key can't be guessed from response timing
    if not hmac.compare_digest(supplied, EXPECTED_DEVICE_KEY.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid or missing device key")


def _key_is_valid(query_key: Optional[str]) -> bool:
    """Non-raising version of _check_device_key, for pages that only need to know whether to unlock."""
    if not EXPECTED_DEVICE_KEY:
        return True
    return hmac.compare_digest((query_key or "").encode("utf-8"), EXPECTED_DEVICE_KEY.encode("utf-8"))


def _dashboard_url(device: Optional[str], key: Optional[str], error: Optional[str] = None) -> str:
    """Where dashboard form posts send the browser back to. The path is fixed; only the values vary."""
    query = []
    if device:
        query.append(f"device={quote(device, safe='')}")
    if key:
        query.append(f"key={quote(key, safe='')}")
    if error:
        query.append(f"error={quote(error, safe='')}")
    return "/dashboard" + ("?" + "&".join(query) if query else "")


def _check_key_or_go_back(x_device_key, key, back, device, cookie_key=None):
    """
    _check_device_key, except that a wrong key from a dashboard button sends the browser
    back to the dashboard with a clear "wrong key" message (and the wrong key dropped from
    the URL) instead of stranding the user on a page of raw JSON. Returns the redirect to
    send, or None if the key is fine. API callers (no back=dashboard) still get a plain 401.
    """
    try:
        _check_device_key(x_device_key, key, cookie_key)
    except HTTPException:
        if back == "dashboard":
            # #demo-controls: land on the key box, where the "incorrect key" message is shown
            return RedirectResponse(_dashboard_url(device, None, error="key") + "#demo-controls", status_code=303)
        raise
    return None


@app.get("/")
def health_check():
    return {"status": "backend is alive", "version": "v2"}


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    # Browsers ask for this on every visit; answering "no icon" (rather than 404) keeps the logs clean.
    return Response(status_code=204)


# --------------------------------------------------------------- ingestion

@app.post("/sensor-data", status_code=202)
def receive_sensor_data(data: SensorData, x_device_key: str = Header(default=None), db: Session = Depends(get_db)):
    """
    Authenticate -> validate (Pydantic already did) -> dedupe -> persist the
    reading -> evaluate rules (pure, no I/O) -> create alert/delivery-job rows
    -> return. No weather/mandi/SMS/voice call happens in this request.
    """
    _check_device_key(x_device_key)
    received_at = datetime.now()

    with devices_repo.INGEST_LOCK:
        # Held through the commit below -- see repositories/devices.INGEST_LOCK
        # for why a bare lock around just the read+mutate step isn't enough
        # once each request has its own DB session/connection.
        accepted, device = devices_repo.accept_sequence(db, data.device_id, data.sequence)
        if not accepted:
            db.rollback()
            return {"accepted": True, "duplicate": True, "reading_id": None, "alerts_created": [], "delivery_jobs_created": []}

        if not devices_repo.verify_secret(device, x_device_key or ""):
            db.rollback()
            raise HTTPException(status_code=401, detail="Invalid device key for this device")
        if not device.enabled:
            db.rollback()
            raise HTTPException(status_code=403, detail="This device is disabled")

        previous_moisture_state = device.moisture_state
        days_since_sowing = compute_days_since_sowing(SOWING_DATE)

        result = evaluate(
            soil_moisture=data.soil_moisture,
            temperature=data.temperature,
            humidity=data.humidity,
            raining=data.raining,
            light_level=data.light_level,
            days_since_sowing=days_since_sowing,
            previous_moisture_state=previous_moisture_state,
        )

        reading = readings_repo.create(
            db, device_id=data.device_id, boot_id=None, sequence=data.sequence,
            soil_moisture=data.soil_moisture, temperature=data.temperature, humidity=data.humidity,
            raining=data.raining, light_level=data.light_level, days_since_sowing=days_since_sowing,
            previous_moisture_state=previous_moisture_state, moisture_state=result["moisture_state"],
            alert_codes=result["alert_codes"], received_at=received_at,
        )
        logging.info(
            "Reading received: device=%s seq=%d moisture=%s temp=%s humidity=%s alerts=%s",
            data.device_id, data.sequence, data.soil_moisture, data.temperature, data.humidity,
            result["alert_codes"],
        )

        new_codes = alerts_repo.get_new_alerts(
            db, data.device_id, result["alert_codes"],
            alert_cooldown_minutes=state_manager.ALERT_COOLDOWN_MINUTES,
            time_based_cooldown_minutes=state_manager.TIME_BASED_ALERT_COOLDOWN_MINUTES,
        )
        alert_events = alerts_repo.create_alert_events(db, data.device_id, reading.id, new_codes)

        devices_repo.save_reading_snapshot(
            db, device, facts=result["facts"], alert_codes=result["alert_codes"],
            moisture_state=result["moisture_state"], updated_at=received_at,
        )

        jobs = delivery_queue.create_delivery_jobs_for_reading(
            db, device, reading, alert_events, new_codes, language=state_manager.get_sms_language(),
        )

        db.commit()

    return {
        "accepted": True,
        "reading_id": reading.id,
        "duplicate": False,
        "days_since_sowing": days_since_sowing,
        "current_alert_codes": result["alert_codes"],
        "alerts_created": new_codes,
        "delivery_jobs_created": [job.id for job in jobs],
    }


def _preview_response(data: SensorData, language: Optional[str] = None) -> dict:
    """
    Never persists, never delivers, never touches device state -- so it can be
    reused freely to preview any combination of values without spending SMS
    quota or disturbing a real device's cooldown/state tracking.
    """
    received_at = datetime.now()
    lang = sms_i18n.normalize_language(language) if language else state_manager.get_sms_language()
    days_since_sowing = compute_days_since_sowing(SOWING_DATE)

    result = evaluate(
        soil_moisture=data.soil_moisture,
        temperature=data.temperature,
        humidity=data.humidity,
        raining=data.raining,
        light_level=data.light_level,
        days_since_sowing=days_since_sowing,
        previous_moisture_state=None,
    )
    new_alerts = [c for c in result["alert_codes"] if c in state_manager.ACTIONABLE_CODES]

    response = {
        "success": True,
        "device_id": "PREVIEW-TEST",
        "timestamp": received_at.isoformat(),
        "sensor": {
            "soil_moisture_index": data.soil_moisture,
            "temperature_c": data.temperature,
            "humidity_percent": data.humidity,
            "rain_detected_now": data.raining,
            "light_level": data.light_level,
        },
        "days_since_sowing": days_since_sowing,
        "current_alert_codes": result["alert_codes"],
        "new_alert_codes": new_alerts,
    }
    if not new_alerts:
        response["action_taken"] = "none (no new or renewed alert conditions)"
        return response

    weather = get_weather()
    mandi = get_mandi_price()
    recent_rainfall = get_recent_rainfall() if "EXCESS_MOISTURE" in new_alerts else None
    result_with_context = evaluate(
        soil_moisture=data.soil_moisture,
        temperature=data.temperature,
        humidity=data.humidity,
        raining=data.raining,
        light_level=data.light_level,
        days_since_sowing=days_since_sowing,
        previous_moisture_state=None,
        weather=weather,
        mandi=mandi,
        recent_rainfall=recent_rainfall,
    )
    facts = result_with_context["facts"]

    response["facts"] = facts
    response["voice_message"] = build_voice_message(new_alerts) if ENABLE_VOICE_CALL else None
    response["sms_language"] = lang
    response["sms_message"] = build_sms_message(result_with_context["alert_codes"], facts, lang=lang, reading_time=received_at)
    if lang != "en":
        response["sms_message_english"] = build_sms_message(result_with_context["alert_codes"], facts, lang="en", reading_time=received_at)
    return response


@app.post("/sensor-data-preview")
def preview_sensor_data(data: SensorData, x_device_key: str = Header(default=None)):
    """
    With PUBLIC_MODE=true this needs a key, because every call fetches
    weather/mandi data and would otherwise let anyone on the internet burn
    those quotas and tie up the server. Locally, no key is needed.
    """
    if PUBLIC_MODE:
        _check_device_key(x_device_key)
    return _preview_response(data)


# --------------------------------------------------------------------- demo

def _run_demo_reading(
    db: Session, device_id: str, sample: SensorData, *,
    days_since_sowing_override: int = None, language: Optional[str] = None, problem_title: Optional[str] = None,
) -> dict:
    """
    The demo path: persists a reading and creates delivery jobs exactly like
    real ingestion, then immediately calls delivery_queue.process_job() for
    each one (the same code the background worker uses) so the response -- and
    the dashboard redirect -- shows the real delivery outcome right away.
    """
    received_at = datetime.now()
    lang = sms_i18n.normalize_language(language) if language else state_manager.get_sms_language()
    days_since_sowing = (
        days_since_sowing_override if days_since_sowing_override is not None
        else compute_days_since_sowing(SOWING_DATE)
    )

    device = devices_repo.get_or_create(db, device_id)
    # The demo device was just reset (state_manager.reset_device), so it always starts fresh.
    previous_moisture_state = None

    result = evaluate(
        soil_moisture=sample.soil_moisture,
        temperature=sample.temperature,
        humidity=sample.humidity,
        raining=sample.raining,
        light_level=sample.light_level,
        days_since_sowing=days_since_sowing,
        previous_moisture_state=previous_moisture_state,
    )
    reading = readings_repo.create(
        db, device_id=device_id, boot_id=None, sequence=sample.sequence,
        soil_moisture=sample.soil_moisture, temperature=sample.temperature, humidity=sample.humidity,
        raining=sample.raining, light_level=sample.light_level, days_since_sowing=days_since_sowing,
        previous_moisture_state=previous_moisture_state, moisture_state=result["moisture_state"],
        alert_codes=result["alert_codes"], received_at=received_at,
    )
    new_codes = alerts_repo.get_new_alerts(
        db, device_id, result["alert_codes"],
        alert_cooldown_minutes=state_manager.ALERT_COOLDOWN_MINUTES,
        time_based_cooldown_minutes=state_manager.TIME_BASED_ALERT_COOLDOWN_MINUTES,
    )
    alert_events = alerts_repo.create_alert_events(db, device_id, reading.id, new_codes, demo_generated=True)
    devices_repo.save_reading_snapshot(
        db, device, facts=result["facts"], alert_codes=result["alert_codes"],
        moisture_state=result["moisture_state"], updated_at=received_at,
    )

    response = {
        "success": True,
        "device_id": device_id,
        "timestamp": received_at.isoformat(),
        "sensor": {
            "soil_moisture_index": sample.soil_moisture,
            "temperature_c": sample.temperature,
            "humidity_percent": sample.humidity,
            "rain_detected_now": sample.raining,
            "light_level": sample.light_level,
        },
        "days_since_sowing": days_since_sowing,
        "current_alert_codes": result["alert_codes"],
        "new_alert_codes": new_codes,
    }

    if not new_codes:
        response["action_taken"] = "none (no new or renewed alert conditions)"
        db.commit()
        return response

    jobs = delivery_queue.create_delivery_jobs_for_reading(
        db, device, reading, alert_events, new_codes, language=lang, test_mode=True, problem_title=problem_title,
    )

    sms_result = voice_result = None
    for job in jobs:
        job_result = delivery_queue.process_job(db, job.id)
        if job_result and job_result["channel"] == "sms":
            sms_result = job_result
        elif job_result and job_result["channel"] == "voice":
            voice_result = job_result

    db.commit()

    facts = (sms_result or voice_result or {}).get("facts", {})
    alert_codes_ctx = (sms_result or voice_result or {}).get("alert_codes", result["alert_codes"])
    response["facts"] = facts
    response["sms_language"] = lang
    if sms_result:
        response["sms_message"] = sms_result["message"]
        if lang != "en":
            response["sms_message_english"] = build_sms_message(alert_codes_ctx, facts, lang="en", reading_time=received_at)
    if ENABLE_VOICE_CALL:
        response["voice_message"] = voice_result["message"] if voice_result else None

    response["delivery"] = {
        "sms_status": sms_result["status_text"] if sms_result else "not attempted",
        "voice_status": voice_result["status_text"] if voice_result else "disabled (SMS-only mode)",
    }
    return response


@app.post("/demo/trigger")
def demo_trigger(x_device_key: str = Header(default=None), db: Session = Depends(get_db)):
    """
    A POST (not GET) endpoint for triggering a real demo call with fixed
    sample values -- deliberately not a GET, since GET requests should never
    have side effects like placing a phone call.
    """
    _check_device_key(x_device_key)
    # A demo must fire EVERY time it is pressed. Forget the DEMO device's cooldown and
    # sequence history first, otherwise the second press within the cooldown does nothing.
    state_manager.reset_device("DEMO")
    sample = SensorData(
        device_id="DEMO",
        sequence=int(datetime.now().timestamp()),
        soil_moisture=20.0,
        temperature=29.5,
        humidity=68.0,
        raining=False,
    )
    return _run_demo_reading(db, "DEMO", sample, problem_title="Low soil moisture (sample)")


@app.get("/demo/scenarios")
def list_demo_scenarios():
    """
    The decision table: every condition the system can alert on, what
    triggers it, and why it matters. The dashboard's demo buttons are built
    from this same data, so the list shown to a judge and the list actually
    wired up to fire can never drift apart.
    """
    return {
        name: {
            "title": s["title"],
            "why_it_matters": s["why_it_matters"],
            "expected_alert": s["expected_alert"],
            "can_force_trigger": s["sensor"] is not None,
        }
        for name, s in demo_scenarios.SCENARIOS.items()
    }


@app.post("/demo/scenario/{name}")
def demo_scenario(
    name: str,
    x_device_key: str = Header(default=None),
    key: str = Query(default=None),
    lang: Optional[str] = Query(default=None),
    back: Optional[str] = Query(default=None),
    device: Optional[str] = Query(default=None),
    advisory_key: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_db),
):
    """
    Introduces ONE specific named problem on demand (see demo_scenarios.py for
    the full decision table), so each alert type can be shown individually
    instead of waiting for it to occur naturally. Each call resets that
    scenario's own simulated device first, so pressing the same button twice in
    a row fires twice -- cooldown logic is for real field devices, not for a
    live demo you're actively controlling. Real devices are never touched.

    `lang` (en/hi/kn) overrides the SMS language for this one call. The
    dashboard's buttons pass `back=dashboard`: the browser is then sent to the
    simulated device's page, where the banner confirms the problem and whether
    the SMS was sent, instead of landing on a page of raw JSON.
    """
    bad_key = _check_key_or_go_back(x_device_key, key, back, device, advisory_key)
    if bad_key:
        return bad_key
    if lang is not None and not sms_i18n.is_supported(lang):
        raise HTTPException(status_code=400, detail=f"Unsupported lang '{lang}'. Use one of: {', '.join(sms_i18n.SUPPORTED_LANGUAGES)}.")

    scenario = demo_scenarios.SCENARIOS.get(name)
    if not scenario:
        raise HTTPException(status_code=404, detail=f"Unknown scenario '{name}'. See GET /demo/scenarios for the list.")
    if scenario["sensor"] is None:
        raise HTTPException(
            status_code=400,
            detail=f"'{name}' cannot be force-triggered: {scenario['why_it_matters']}",
        )

    demo_device_id = f"DEMO-{name.upper()}"
    state_manager.reset_device(demo_device_id)

    sample = SensorData(
        device_id=demo_device_id,
        sequence=int(datetime.now().timestamp()),
        **scenario["sensor"],
    )
    result = _run_demo_reading(
        db, demo_device_id, sample, days_since_sowing_override=scenario["days_override"],
        language=lang.strip().lower() if lang else None, problem_title=scenario["title"],
    )
    result["scenario"] = name
    result["expected_alert"] = scenario["expected_alert"]
    if back == "dashboard":
        return RedirectResponse(_dashboard_url(demo_device_id, None), status_code=303)
    return result


@app.post("/demo/test-real-sms")
def test_real_sms(
    device: str = Query(...),
    x_device_key: str = Header(default=None),
    key: str = Query(default=None),
    back: Optional[str] = Query(default=None),
    advisory_key: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_db),
):
    """
    Force-sends a real SMS built from a REAL device's most recent ACTUAL reading --
    bypassing the alert cooldown -- so the exact wording and delivery can be checked
    against today's genuine field numbers, instead of a /demo/* button's fixed
    sample values. Never fabricates a problem: only sends if that reading's real
    values currently imply at least one alert condition (the rule engine decides,
    same as a real ingestion would).
    """
    bad_key = _check_key_or_go_back(x_device_key, key, back, device, advisory_key)
    if bad_key:
        return bad_key

    recent = readings_repo.recent(db, device, limit=1)
    reading = recent[0] if recent else None
    alert_codes = []
    if reading is not None:
        result = evaluate(
            soil_moisture=reading.soil_moisture,
            temperature=reading.temperature,
            humidity=reading.humidity,
            raining=reading.raining,
            light_level=reading.light_level,
            days_since_sowing=reading.days_since_sowing,
            previous_moisture_state=reading.previous_moisture_state,
        )
        alert_codes = result["alert_codes"]

    if not alert_codes:
        if back == "dashboard":
            return RedirectResponse(_dashboard_url(device, None, error="no-problem"), status_code=303)
        return {"sent": False, "reason": "No active alert on this device's most recent real reading."}

    dev = devices_repo.get(db, device)
    alert_events = alerts_repo.create_alert_events(db, device, reading.id, alert_codes, demo_generated=True)
    # test_mode=False deliberately: this is real device data and a real alert condition, just
    # force-sent past the cooldown -- it should look exactly like a genuine advisory (no "[TEST]"
    # prefix, no "made-up readings" banner text), not like a /demo/* button's synthetic scenario.
    jobs = delivery_queue.create_delivery_jobs_for_reading(
        db, dev, reading, alert_events, alert_codes, language=state_manager.get_sms_language(),
    )
    db.commit()

    sms_result = None
    for job in jobs:
        job_result = delivery_queue.process_job(db, job.id)
        if job_result and job_result["channel"] == "sms":
            sms_result = job_result
    db.commit()

    if back == "dashboard":
        return RedirectResponse(_dashboard_url(device, None), status_code=303)
    return {
        "sent": bool(sms_result and sms_result["success"]),
        "alert_codes": alert_codes,
        "sms_message": sms_result["message"] if sms_result else None,
        "sms_status": sms_result["status_text"] if sms_result else None,
    }


@app.post("/demo/reset")
def back_to_real_values(
    x_device_key: str = Header(default=None),
    key: str = Query(default=None),
    back: Optional[str] = Query(default=None),
    advisory_key: Optional[str] = Cookie(default=None),
):
    """
    Clears every simulated problem (the DEMO-* devices and their notification) and returns
    to the real field readings. Real devices, their alert state and the SMS language are untouched.
    """
    bad_key = _check_key_or_go_back(x_device_key, key, back, None, advisory_key)
    if bad_key:
        return bad_key
    state_manager.clear_simulation()
    if back == "dashboard":
        return RedirectResponse(_dashboard_url(None, None), status_code=303)
    return {"reset": True}


@app.post("/settings/sms-language")
def set_sms_language(
    lang: str = Query(...),
    x_device_key: str = Header(default=None),
    key: str = Query(default=None),
    back: Optional[str] = Query(default=None),
    device: Optional[str] = Query(default=None),
    advisory_key: Optional[str] = Cookie(default=None),
):
    """
    Sets the language (en / hi / kn) of every SMS from now on -- automatic ones
    and the demo buttons alike -- until the server restarts (then TRANSLATE_SMS_TO
    from .env applies again). Needs the device key, like every other action that
    changes what gets sent to a phone.
    """
    bad_key = _check_key_or_go_back(x_device_key, key, back, device, advisory_key)
    if bad_key:
        return bad_key
    if not sms_i18n.is_supported(lang):
        raise HTTPException(status_code=400, detail=f"Unsupported lang '{lang}'. Use one of: {', '.join(sms_i18n.SUPPORTED_LANGUAGES)}.")
    state_manager.set_sms_language(lang)
    if back == "dashboard":
        return RedirectResponse(_dashboard_url(device, None), status_code=303)
    return {"sms_language": state_manager.get_sms_language()}


@app.post("/dashboard/lock")
def lock_dashboard():
    """Forget the remembered access key: the dashboard's controls lock again."""
    response = RedirectResponse("/dashboard", status_code=303)
    response.delete_cookie(_KEY_COOKIE, path="/")
    return response


# Defence in depth for the dashboard: no scripts, no external loads, no framing.
# form-action 'self' lets the dashboard's own <form> buttons post to this server
# (and only this server); 'none' would make browsers silently refuse every button.
_DASHBOARD_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    # the access key can be in this page's URL for a moment: never hand it to other sites via the Referer header
    "Referrer-Policy": "no-referrer",
}


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    device: Optional[str] = None,
    key: Optional[str] = None,
    error: Optional[str] = None,
    unlock: Optional[str] = None,
    advisory_key: Optional[str] = Cookie(default=None),
):
    # Entering the access key (the box on the page, or ?key=...) unlocks the controls ONCE: the right key
    # is remembered in a cookie and dropped from the URL, so it does not sit in the address bar, browser
    # history or server logs, and the buttons keep working across page reloads. Still: don't share a
    # dashboard link that contains ?key=..., and rotate EXPECTED_DEVICE_KEY if one is ever exposed.
    if key and _key_is_valid(key):
        response = RedirectResponse(_dashboard_url(device, None), status_code=303)
        response.set_cookie(
            _KEY_COOKIE, key, max_age=_KEY_COOKIE_MAX_AGE, httponly=True, samesite="strict",
            secure=PUBLIC_MODE, path="/",
        )
        return response

    # A wrong key never unlocks anything; the page says so (a button press with a wrong key is
    # redirected here with error=key).
    unlocked = _key_is_valid(advisory_key)
    key_error = (error == "key" or bool(key)) and not unlocked
    return HTMLResponse(
        render_dashboard(device, unlocked=unlocked, key_error=key_error, unlock=bool(unlock), error=error),
        headers=_DASHBOARD_HEADERS,
    )


# --------------------------------------------------------- background worker

if ENABLE_DELIVERY_WORKER:
    worker.start()
