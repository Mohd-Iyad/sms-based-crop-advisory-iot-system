"""
API / pipeline tests for main.py, run in-process with FastAPI's TestClient.

Every outbound call (Twilio/textbee SMS, voice call, Open-Meteo, data.gov.in,
Gemini) is mocked, so these run offline, instantly, and can never send a real
SMS or place a real call regardless of what is in .env.

v3 architecture note: /sensor-data now returns HTTP 202 immediately and never
calls weather/mandi/SMS/voice inline -- those happen later, in
services/delivery_queue.py, either via the background worker (disabled in
tests -- see tests/conftest.py) or explicitly via
delivery_queue.process_all_pending(), which tests call once they want to
observe the delivery outcome. Demo endpoints (/demo/trigger,
/demo/scenario/{name}) still deliver synchronously, so their responses keep
the old delivery/sms_message/voice_message shape.
"""
import os
import sys
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
import state_manager
import services.delivery_queue as delivery_queue

KEY = {"X-Device-Key": "test-key"}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """Fresh state (see tests/conftest.py) + deterministic config + all network mocked, for every test."""
    client.cookies.clear()          # the dashboard remembers the access key in a cookie: start every test locked
    monkeypatch.setattr(state_manager, "TRANSLATE_SMS_TO", "")   # whatever .env says: default to English

    monkeypatch.setattr(main, "EXPECTED_DEVICE_KEY", "test-key")
    # Day 5 of the crop: no fertilizer / harvest rule fires, so only moisture
    # and sensor-fault codes drive the tests.
    monkeypatch.setattr(main, "SOWING_DATE", (date.today() - timedelta(days=5)).isoformat())
    monkeypatch.setattr(main, "ENABLE_VOICE_CALL", False)
    monkeypatch.setattr(delivery_queue, "ENABLE_VOICE_CALL", False)
    monkeypatch.setattr(state_manager, "ALERT_COOLDOWN_MINUTES", 720)

    calls = {"sms": [], "voice": []}

    def fake_sms(message, **_):
        calls["sms"].append(message)
        return {"success": True, "status_code": 201}

    def fake_voice(message, **_):
        calls["voice"].append(message)
        return {"success": True, "status_code": 201}

    weather_ok = lambda: {"available": True, "rain_expected": False, "forecast": []}
    mandi_off = lambda: {"available": False}
    rainfall_off = lambda: {"available": False, "rained_recently": None, "mm_last_6h": None}

    # Delivery (the real, async path): everything lives in delivery_queue now.
    monkeypatch.setattr(delivery_queue, "send_sms", fake_sms)
    monkeypatch.setattr(delivery_queue, "make_voice_call", fake_voice)
    monkeypatch.setattr(delivery_queue, "get_weather", weather_ok)
    monkeypatch.setattr(delivery_queue, "get_mandi_price", mandi_off)
    monkeypatch.setattr(delivery_queue, "get_recent_rainfall", rainfall_off)
    monkeypatch.setattr(delivery_queue, "build_voice_message", lambda codes: "VOICE:" + ",".join(codes))

    # Preview (/sensor-data-preview): a separate, still-synchronous code path in main.py.
    monkeypatch.setattr(main, "get_weather", weather_ok)
    monkeypatch.setattr(main, "get_mandi_price", mandi_off)
    monkeypatch.setattr(main, "get_recent_rainfall", rainfall_off)
    monkeypatch.setattr(main, "build_voice_message", lambda codes: "VOICE:" + ",".join(codes))

    yield calls


client = TestClient(main.app)


def reading(seq, moisture=50.0, **kw):
    body = {
        "device_id": "FIELD-001", "sequence": seq, "soil_moisture": moisture,
        "temperature": 28.0, "humidity": 60.0, "raining": False,
    }
    body.update(kw)
    return body


# ---------------------------------------------------------------- basics

def test_health():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json() == {"status": "backend is alive", "version": "v2"}


def test_get_on_demo_trigger_is_not_allowed():
    assert client.get("/demo/trigger").status_code == 405


# ------------------------------------------------------------------ auth

def test_sensor_data_requires_device_key(isolated):
    assert client.post("/sensor-data", json=reading(1, 20)).status_code == 401
    assert client.post("/sensor-data", json=reading(1, 20), headers={"X-Device-Key": "bad"}).status_code == 401
    assert isolated["sms"] == []


def test_demo_trigger_requires_device_key(isolated):
    assert client.post("/demo/trigger").status_code == 401
    assert isolated["sms"] == []


def test_auth_check_skipped_when_key_not_configured(monkeypatch, isolated):
    monkeypatch.setattr(main, "EXPECTED_DEVICE_KEY", "")
    r = client.post("/sensor-data", json=reading(1, 20))
    assert r.status_code == 202
    delivery_queue.process_all_pending()
    assert len(isolated["sms"]) == 1


# ------------------------------------------------------------ validation

@pytest.mark.parametrize("patch", [
    {"soil_moisture": 101}, {"soil_moisture": -1},
    {"temperature": 61}, {"temperature": -11},
    {"humidity": 101}, {"light_level": 101},
    {"sequence": -1}, {"sequence": "abc"}, {"device_id": ""},
])
def test_out_of_range_or_bad_values_rejected(patch):
    assert client.post("/sensor-data-preview", json=reading(1, **patch)).status_code == 422


def test_missing_device_id_rejected():
    body = reading(1)
    del body["device_id"]
    assert client.post("/sensor-data-preview", json=body).status_code == 422


def test_boundary_values_accepted():
    for patch in ({"soil_moisture": 0}, {"soil_moisture": 100}, {"temperature": -10}, {"temperature": 60}):
        assert client.post("/sensor-data-preview", json=reading(1, **patch)).status_code == 200


# --------------------------------------------------------------- preview

def test_preview_never_delivers_and_shows_message(isolated):
    r = client.post("/sensor-data-preview", json=reading(1, 20))
    body = r.json()
    assert r.status_code == 200
    assert body["device_id"] == "PREVIEW-TEST"
    assert "LOW_MOISTURE" in body["new_alert_codes"]
    assert "soil moisture is low" in body["sms_message"]
    assert "delivery" not in body
    assert isolated["sms"] == [] and isolated["voice"] == []


def test_preview_is_repeatable_and_leaves_no_state(isolated):
    for _ in range(3):
        r = client.post("/sensor-data-preview", json=reading(1, 20))
        assert "LOW_MOISTURE" in r.json()["new_alert_codes"]
    assert state_manager.get_all_device_ids() == []
    assert "Waiting for the first sensor reading" in client.get("/dashboard").text


def test_preview_healthy_field_takes_no_action():
    body = client.post("/sensor-data-preview", json=reading(1, 50)).json()
    assert body["new_alert_codes"] == []
    assert body["action_taken"].startswith("none")
    assert "sms_message" not in body


def test_preview_sensor_faults_are_reported_not_faked():
    body = client.post(
        "/sensor-data-preview",
        json={"device_id": "X", "sequence": 1, "soil_moisture": None, "temperature": None, "humidity": None},
    ).json()
    assert {"SENSOR_FAULT_DHT22", "SENSOR_FAULT_SOIL"} <= set(body["new_alert_codes"])
    assert "Temperature:" not in body["sms_message"]
    assert "Humidity:" not in body["sms_message"]


def test_preview_excess_moisture():
    body = client.post("/sensor-data-preview", json=reading(1, 90)).json()
    assert "EXCESS_MOISTURE" in body["new_alert_codes"]


# ------------------------------------------------------------- delivery

def test_real_reading_with_new_alert_sends_one_sms(isolated):
    r = client.post("/sensor-data", json=reading(1, 20), headers=KEY)
    body = r.json()
    assert r.status_code == 202
    assert body["alerts_created"] == ["LOW_MOISTURE"]
    delivery_queue.process_all_pending()
    assert len(isolated["sms"]) == 1
    assert isolated["voice"] == []
    snap = state_manager.get_snapshot("FIELD-001")
    assert snap["delivery"] == {"voice_status": "disabled (SMS-only mode)", "sms_status": "sent"}


def test_healthy_reading_sends_nothing(isolated):
    body = client.post("/sensor-data", json=reading(1, 50), headers=KEY).json()
    assert body["alerts_created"] == []
    delivery_queue.process_all_pending()
    assert isolated["sms"] == []


def test_same_condition_does_not_realert_within_cooldown(isolated):
    """The core v2 fix: a dry field must not text every 5 minutes."""
    for seq in range(1, 6):
        client.post("/sensor-data", json=reading(seq, 20), headers=KEY)
    delivery_queue.process_all_pending()
    assert len(isolated["sms"]) == 1


def test_realerts_after_cooldown_expires(monkeypatch, isolated):
    monkeypatch.setattr(state_manager, "ALERT_COOLDOWN_MINUTES", 0)
    client.post("/sensor-data", json=reading(1, 20), headers=KEY)
    client.post("/sensor-data", json=reading(2, 20), headers=KEY)
    delivery_queue.process_all_pending()
    assert len(isolated["sms"]) == 2


def test_realerts_when_condition_clears_then_returns(isolated):
    client.post("/sensor-data", json=reading(1, 20), headers=KEY)   # low -> alert
    client.post("/sensor-data", json=reading(2, 50), headers=KEY)   # back to normal
    client.post("/sensor-data", json=reading(3, 20), headers=KEY)   # low again -> alert
    delivery_queue.process_all_pending()
    assert len(isolated["sms"]) == 2


def test_duplicate_or_retried_sequence_ignored(isolated):
    client.post("/sensor-data", json=reading(5, 20), headers=KEY)
    dup = client.post("/sensor-data", json=reading(5, 20), headers=KEY).json()
    older = client.post("/sensor-data", json=reading(4, 20), headers=KEY).json()
    assert dup["duplicate"] is True and older["duplicate"] is True
    delivery_queue.process_all_pending()
    assert len(isolated["sms"]) == 1


def test_sequences_tracked_per_device(isolated):
    client.post("/sensor-data", json=reading(1, 20, device_id="A"), headers=KEY)
    r = client.post("/sensor-data", json=reading(1, 20, device_id="B"), headers=KEY).json()
    assert r["duplicate"] is False
    delivery_queue.process_all_pending()
    assert len(isolated["sms"]) == 2


def test_moisture_hysteresis_through_the_api(isolated):
    """27 -> low (alert); 30 and 34 stay low (no new alert); 36 -> normal."""
    client.post("/sensor-data", json=reading(1, 27), headers=KEY)
    r30 = client.post("/sensor-data", json=reading(2, 30), headers=KEY).json()
    r34 = client.post("/sensor-data", json=reading(3, 34), headers=KEY).json()
    r36 = client.post("/sensor-data", json=reading(4, 36), headers=KEY).json()
    assert "LOW_MOISTURE" in r30["current_alert_codes"]
    assert "LOW_MOISTURE" in r34["current_alert_codes"]
    assert "LOW_MOISTURE" not in r36["current_alert_codes"]
    delivery_queue.process_all_pending()
    assert len(isolated["sms"]) == 1


def test_sms_failure_is_reported_not_swallowed(monkeypatch):
    monkeypatch.setattr(delivery_queue, "send_sms", lambda m, **_: {"success": False, "error": "Twilio 21608: unverified", "retryable": False})
    client.post("/sensor-data", json=reading(1, 20), headers=KEY)
    delivery_queue.process_all_pending()
    snap = state_manager.get_snapshot("FIELD-001")
    assert snap["delivery"]["sms_status"] == "failed: Twilio 21608: unverified"


def test_voice_enabled_sends_call_and_sms(monkeypatch, isolated):
    monkeypatch.setattr(delivery_queue, "ENABLE_VOICE_CALL", True)
    client.post("/sensor-data", json=reading(1, 20), headers=KEY)
    delivery_queue.process_all_pending()
    assert isolated["voice"] == ["VOICE:LOW_MOISTURE"]
    assert len(isolated["sms"]) == 1
    snap = state_manager.get_snapshot("FIELD-001")
    assert snap["delivery"]["voice_status"] == "sent"


def test_voice_failure_does_not_block_sms(monkeypatch, isolated):
    monkeypatch.setattr(delivery_queue, "ENABLE_VOICE_CALL", True)
    monkeypatch.setattr(delivery_queue, "make_voice_call", lambda m, **_: {"success": False, "status_code": 500, "retryable": False})
    client.post("/sensor-data", json=reading(1, 20), headers=KEY)
    delivery_queue.process_all_pending()
    snap = state_manager.get_snapshot("FIELD-001")
    assert snap["delivery"]["voice_status"] == "failed: 500"
    assert snap["delivery"]["sms_status"] == "sent"


def test_demo_trigger_delivers_with_key(isolated):
    r = client.post("/demo/trigger", headers=KEY)
    assert r.status_code == 200
    assert r.json()["device_id"] == "DEMO"
    assert len(isolated["sms"]) == 1


# ------------------------------------------- weather / mandi in the message

def test_weather_failure_says_unavailable_never_no_rain(monkeypatch, isolated):
    monkeypatch.setattr(delivery_queue, "get_weather", lambda: {"available": False, "rain_expected": None, "forecast": None})
    client.post("/sensor-data", json=reading(1, 20), headers=KEY)
    delivery_queue.process_all_pending()
    sms = isolated["sms"][0]
    snap = state_manager.get_snapshot("FIELD-001")
    assert snap["facts"]["rain_expected_next_days"] is None
    assert "Weather forecast unavailable" in sms
    assert "No significant rain" not in sms


def test_mandi_price_included_when_available(monkeypatch, isolated):
    monkeypatch.setattr(delivery_queue, "get_mandi_price", lambda: {
        "available": True, "market": "Bhatkal", "arrival_date": "21/09/2026", "modal_price": 2300.0,
    })
    client.post("/sensor-data", json=reading(1, 20), headers=KEY)
    delivery_queue.process_all_pending()
    assert "Mandi (Bhatkal, 21/09/2026): Rs 2300.0/quintal" in isolated["sms"][0]


def test_mandi_alone_never_triggers_a_message(monkeypatch, isolated):
    monkeypatch.setattr(delivery_queue, "get_mandi_price", lambda: {"available": True, "market": "M", "modal_price": 1.0})
    client.post("/sensor-data", json=reading(1, 50), headers=KEY)
    delivery_queue.process_all_pending()
    assert isolated["sms"] == []


# The dashboard's rendering is covered in tests/test_dashboard.py.


# --------------------------------------- rain-vs-irrigation cross-verification

def test_excess_moisture_confirmed_as_rain(monkeypatch, isolated):
    monkeypatch.setattr(
        delivery_queue, "get_recent_rainfall",
        lambda: {"available": True, "rained_recently": True, "mm_last_6h": 12.4},
    )
    client.post("/sensor-data", json=reading(1, 85), headers=KEY)
    delivery_queue.process_all_pending()
    snap = state_manager.get_snapshot("FIELD-001")
    assert snap["facts"]["moisture_source"] == "rain"
    assert "recent rainfall" in isolated["sms"][0]
    assert "irrigation" not in isolated["sms"][0].lower() or "not rain" not in isolated["sms"][0].lower()


def test_excess_moisture_attributed_to_irrigation(monkeypatch, isolated):
    monkeypatch.setattr(
        delivery_queue, "get_recent_rainfall",
        lambda: {"available": True, "rained_recently": False, "mm_last_6h": 0.0},
    )
    client.post("/sensor-data", json=reading(1, 85), headers=KEY)
    delivery_queue.process_all_pending()
    snap = state_manager.get_snapshot("FIELD-001")
    assert snap["facts"]["moisture_source"] == "irrigation"
    assert "irrigation" in isolated["sms"][0].lower()
    assert "overwatering" in isolated["sms"][0].lower()


def test_excess_moisture_unknown_when_weather_check_fails(isolated):
    # isolated's default get_recent_rainfall mock already returns unavailable.
    client.post("/sensor-data", json=reading(1, 85), headers=KEY)
    delivery_queue.process_all_pending()
    snap = state_manager.get_snapshot("FIELD-001")
    assert snap["facts"]["moisture_source"] == "unknown"
    assert "Could not confirm whether this is rain or irrigation" in isolated["sms"][0]


def test_recent_rainfall_never_fetched_for_low_moisture(monkeypatch, isolated):
    """Fetching real (observed) rainfall data only makes sense for EXCESS_MOISTURE."""
    calls = []
    monkeypatch.setattr(delivery_queue, "get_recent_rainfall", lambda: calls.append(1) or {"available": False, "rained_recently": None, "mm_last_6h": None})
    client.post("/sensor-data", json=reading(1, 15), headers=KEY)  # LOW_MOISTURE, not EXCESS
    delivery_queue.process_all_pending()
    assert calls == []


# ------------------------------------------------------- demo scenario endpoints

def test_list_demo_scenarios_matches_the_decision_table():
    body = client.get("/demo/scenarios").json()
    assert "low_moisture" in body
    assert body["low_moisture"]["expected_alert"] == "LOW_MOISTURE"
    assert body["rain_warning"]["can_force_trigger"] is False
    assert body["low_moisture"]["can_force_trigger"] is True


def test_demo_scenario_requires_device_key(isolated):
    r = client.post("/demo/scenario/low_moisture")
    assert r.status_code == 401


def test_demo_scenario_accepts_key_via_query_param(isolated):
    """HTML <form> buttons can't set custom headers without JavaScript."""
    r = client.post("/demo/scenario/low_moisture?key=test-key")
    assert r.status_code == 200
    assert r.json()["expected_alert"] == "LOW_MOISTURE"
    assert "LOW_MOISTURE" in r.json()["new_alert_codes"]


def test_demo_scenario_fires_every_time_like_demo_trigger(isolated):
    r1 = client.post("/demo/scenario/low_moisture", headers=KEY)
    r2 = client.post("/demo/scenario/low_moisture", headers=KEY)
    assert "LOW_MOISTURE" in r1.json()["new_alert_codes"]
    assert "LOW_MOISTURE" in r2.json()["new_alert_codes"]  # not suppressed by cooldown
    assert len(isolated["sms"]) == 2


def test_demo_scenario_unknown_name_is_404(isolated):
    r = client.post("/demo/scenario/not_a_real_scenario", headers=KEY)
    assert r.status_code == 404


def test_demo_scenario_rain_warning_cannot_be_force_triggered(isolated):
    r = client.post("/demo/scenario/rain_warning", headers=KEY)
    assert r.status_code == 400
    assert "cannot be force-triggered" in r.json()["detail"]


def test_demo_scenario_fertilizer_uses_days_override_not_real_sowing_date(isolated):
    body = client.post("/demo/scenario/fertilizer_tillering", headers=KEY).json()
    assert body["days_since_sowing"] == 20
    assert "FERTILIZER_DUE_TILLERING" in body["new_alert_codes"]


def test_demo_scenario_sensor_fault_reports_honestly(isolated):
    body = client.post("/demo/scenario/sensor_fault_dht", headers=KEY).json()
    assert "SENSOR_FAULT_DHT22" in body["new_alert_codes"]
    assert body["facts"]["temperature_c"] is None


def test_real_sensor_data_is_never_affected_by_demo_days_override(isolated):
    """A demo scenario call must not leak its days-override into real readings."""
    client.post("/demo/scenario/fertilizer_panicle", headers=KEY)  # days_override=45
    body = client.post("/sensor-data", json=reading(1, 50), headers=KEY).json()
    assert body["days_since_sowing"] == 5  # from the isolated fixture's real SOWING_DATE


# ---------------------------------------------------------------- SMS language

def test_sms_is_english_by_default(isolated):
    client.post("/sensor-data", json=reading(1, 15), headers=KEY)
    delivery_queue.process_all_pending()
    assert "Soil moisture index" in isolated["sms"][0]


def test_sms_uses_the_env_default_language(monkeypatch, isolated):
    monkeypatch.setattr(state_manager, "TRANSLATE_SMS_TO", "kn")
    client.post("/sensor-data", json=reading(1, 15), headers=KEY)
    delivery_queue.process_all_pending()
    assert isolated["sms"][0].startswith("ಬೆಳೆ ಸಲಹೆ")


def test_unsupported_env_language_falls_back_to_english(monkeypatch, isolated):
    monkeypatch.setattr(state_manager, "TRANSLATE_SMS_TO", "fr")
    client.post("/sensor-data", json=reading(1, 15), headers=KEY)
    delivery_queue.process_all_pending()
    assert isolated["sms"][0].startswith("CROP ADVISORY")


@pytest.mark.parametrize("lang", ["hi", "kn"])
def test_indic_sms_keeps_every_number_as_ascii_digits(lang, isolated):
    """No translator is involved, so the values can never be altered or rendered in native digits."""
    client.post(f"/settings/sms-language?lang={lang}", headers=KEY)
    client.post("/sensor-data", json=reading(1, 15.0), headers=KEY)
    delivery_queue.process_all_pending()
    sms = isolated["sms"][0]
    for expected in ("15/100", "28.0", "60%"):
        assert expected in sms
    # neither Devanagari (U+0966-096F) nor Kannada (U+0CE6-0CEF) digits
    assert not any("०" <= ch <= "९" or "೦" <= ch <= "೯" for ch in sms)


def test_sms_carries_the_reading_time(isolated):
    client.post("/sensor-data", json=reading(1, 15), headers=KEY)
    delivery_queue.process_all_pending()
    assert "Reading: " in isolated["sms"][0]


def test_set_language_requires_the_device_key(isolated):
    assert client.post("/settings/sms-language?lang=kn").status_code == 401
    assert state_manager.get_sms_language() == "en"


def test_set_language_rejects_unsupported_codes(isolated):
    r = client.post("/settings/sms-language?lang=fr", headers=KEY)
    assert r.status_code == 400
    assert state_manager.get_sms_language() == "en"


def test_set_language_changes_every_following_sms(isolated):
    r = client.post("/settings/sms-language?lang=hi&key=test-key")
    assert r.status_code == 200 and r.json() == {"sms_language": "hi"}
    client.post("/sensor-data", json=reading(1, 15), headers=KEY)
    delivery_queue.process_all_pending()
    assert isolated["sms"][0].startswith("फसल सलाह")
    # a demo button uses the same setting
    demo = client.post("/demo/scenario/low_moisture", headers=KEY).json()
    assert demo["sms_language"] == "hi"


def test_demo_scenario_lang_param_overrides_for_one_call(isolated):
    body = client.post("/demo/scenario/low_moisture?lang=kn", headers=KEY).json()
    assert body["sms_language"] == "kn"
    assert state_manager.get_sms_language() == "en"     # the saved setting is untouched
    assert client.post("/demo/scenario/low_moisture?lang=fr", headers=KEY).status_code == 400


def test_dashboard_form_posts_redirect_back_to_the_dashboard(isolated):
    r = client.post("/demo/scenario/sensor_fault_dht?key=test-key&back=dashboard&device=FIELD-001",
                    follow_redirects=False)
    assert r.status_code == 303
    # it opens the simulated device's page, where the problem is visible (not the device you were on)
    assert r.headers["location"] == "/dashboard?device=DEMO-SENSOR_FAULT_DHT"
    assert len(isolated["sms"]) == 1                    # and the SMS really was sent

    r = client.post("/settings/sms-language?lang=kn&key=test-key&back=dashboard&device=FIELD-001", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard?device=FIELD-001"      # the access key is not put in the URL


# ------------------------------------------------------- last-SMS outcome (dashboard banner)

def test_sms_event_recorded_on_success(isolated):
    client.post("/demo/scenario/sensor_fault_dht", headers=KEY)
    event = state_manager.get_last_sms_event()
    assert event["ok"] is True and event["error"] is None
    assert event["device_id"] == "DEMO-SENSOR_FAULT_DHT"
    assert event["message"] == isolated["sms"][0]


def test_sms_event_recorded_on_failure(monkeypatch, isolated):
    monkeypatch.setattr(delivery_queue, "send_sms", lambda m, **_: {"success": False, "error": "textbee 401: bad key", "retryable": False})
    client.post("/demo/scenario/sensor_fault_dht", headers=KEY)
    event = state_manager.get_last_sms_event()
    assert event["ok"] is False and event["error"] == "textbee 401: bad key"


def test_no_sms_event_when_nothing_was_sent(isolated):
    client.post("/sensor-data", json=reading(1, 50), headers=KEY)    # nothing to alert on
    assert state_manager.get_last_sms_event() is None


# --------------------------------------------------------------- dashboard CSP

def test_dashboard_csp_allows_its_own_form_posts():
    csp = client.get("/dashboard").headers["content-security-policy"]
    assert "form-action 'self'" in csp
    assert "form-action 'none'" not in csp


# -------------------------------------------------- wrong key from a dashboard button

def test_wrong_key_from_a_dashboard_button_goes_back_with_a_message_and_sends_nothing(isolated):
    r = client.post("/demo/scenario/sensor_fault_dht?key=FIELD-001&back=dashboard&device=FIELD-001",
                    follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard?device=FIELD-001&error=key#demo-controls"   # the wrong key is dropped
    assert isolated["sms"] == []
    assert state_manager.get_last_sms_event() is None


def test_wrong_key_from_a_language_chip_goes_back_and_changes_nothing(isolated):
    r = client.post("/settings/sms-language?lang=kn&key=nope&back=dashboard", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/dashboard?error=key#demo-controls"
    assert state_manager.get_sms_language() == "en"


def test_wrong_key_for_api_callers_is_still_a_plain_401(isolated):
    assert client.post("/demo/scenario/low_moisture?key=nope").status_code == 401
    assert client.post("/settings/sms-language?lang=kn&key=nope").status_code == 401
    assert isolated["sms"] == []
