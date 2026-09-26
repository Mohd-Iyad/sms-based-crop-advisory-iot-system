"""
Tests for the modules that talk to outside services (telephony, weather,
mandi, llm) plus the SMS template. `requests` is mocked everywhere, so no
real network call is ever made.
"""
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llm
import mandi
import message_planner
import telephony
import weather


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


def boom(*a, **k):
    raise requests.ConnectionError("network down")


# -------------------------------------------------------------- telephony

def test_twilio_sms_success(monkeypatch):
    seen = {}

    def fake_post(url, data=None, auth=None, timeout=None, **kw):
        seen.update(url=url, data=data, timeout=timeout)
        return FakeResponse(201, {"sid": "SM123"})

    monkeypatch.setattr(telephony, "SMS_PROVIDER", "twilio")
    monkeypatch.setattr(telephony.requests, "post", fake_post)
    r = telephony.send_sms("hello")
    assert r["success"] is True
    assert seen["url"].endswith("/Messages.json")
    assert seen["data"]["Body"] == "hello"
    assert seen["timeout"] == telephony.REQUEST_TIMEOUT_SECONDS


def test_twilio_sms_error_surfaces_code_and_message(monkeypatch):
    monkeypatch.setattr(telephony, "SMS_PROVIDER", "twilio")
    monkeypatch.setattr(
        telephony.requests, "post",
        lambda *a, **k: FakeResponse(400, {"code": 572006, "message": "templates only"}),
    )
    r = telephony.send_sms("x")
    assert r["success"] is False
    assert r["error"] == "Twilio 572006: templates only"


def test_sms_never_raises_on_network_failure(monkeypatch):
    monkeypatch.setattr(telephony, "SMS_PROVIDER", "twilio")
    monkeypatch.setattr(telephony.requests, "post", boom)
    r = telephony.send_sms("x")
    assert r["success"] is False and "network down" in r["error"]


def test_textbee_routing_and_payload(monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        seen.update(url=url, json=json, headers=headers)
        return FakeResponse(200, {"ok": True})

    monkeypatch.setattr(telephony, "SMS_PROVIDER", "textbee")
    monkeypatch.setattr(telephony, "TEXTBEE_API_KEY", "k")
    monkeypatch.setattr(telephony, "TEXTBEE_DEVICE_ID", "dev1")
    monkeypatch.setattr(telephony, "ADVISORY_TO_NUMBER", "+910000000000")
    monkeypatch.setattr(telephony.requests, "post", fake_post)
    assert telephony.send_sms("hi")["success"] is True
    assert seen["url"] == telephony.TEXTBEE_SEND_URL
    assert seen["headers"] == {"x-api-key": "k"}
    assert seen["json"] == {"recipients": ["+910000000000"], "message": "hi", "deviceId": "dev1"}


def test_textbee_failure_and_non_json_body(monkeypatch):
    monkeypatch.setattr(telephony, "SMS_PROVIDER", "textbee")
    monkeypatch.setattr(telephony.requests, "post", lambda *a, **k: FakeResponse(401, None, "Unauthorized"))
    r = telephony.send_sms("x")
    assert r["success"] is False and r["error"].startswith("textbee 401")


def test_voice_call_escapes_xml_and_uses_configured_voice(monkeypatch):
    seen = {}

    def fake_post(url, data=None, **kw):
        seen.update(url=url, data=data)
        return FakeResponse(201, {"sid": "CA1"})

    monkeypatch.setattr(telephony.requests, "post", fake_post)
    r = telephony.make_voice_call("Rain & wind <soon>")
    assert r["success"] is True
    assert seen["url"].endswith("/Calls.json")
    twiml = seen["data"]["Twiml"]
    assert "Rain &amp; wind &lt;soon&gt;" in twiml
    assert f'voice="{telephony.TWILIO_VOICE}"' in twiml


def test_voice_call_never_raises(monkeypatch):
    monkeypatch.setattr(telephony.requests, "post", boom)
    assert telephony.make_voice_call("x")["success"] is False


# ---------------------------------------------------------------- weather

def test_weather_rain_expected_at_threshold(monkeypatch):
    data = {"daily": {"time": ["d1", "d2", "d3"], "precipitation_sum": [0.0, 5.0, 1.0]}}
    monkeypatch.setattr(weather.requests, "get", lambda *a, **k: FakeResponse(200, data))
    w = weather.get_weather()
    assert w["available"] is True and w["rain_expected"] is True
    assert w["forecast"][1] == {"date": "d2", "rain_mm": 5.0}


def test_weather_no_rain(monkeypatch):
    data = {"daily": {"time": ["d1"], "precipitation_sum": [4.9]}}
    monkeypatch.setattr(weather.requests, "get", lambda *a, **k: FakeResponse(200, data))
    assert weather.get_weather()["rain_expected"] is False


@pytest.mark.parametrize("getter", [boom, lambda *a, **k: FakeResponse(500, {})])
def test_weather_failure_is_unknown_not_false(monkeypatch, getter):
    monkeypatch.setattr(weather.requests, "get", getter)
    w = weather.get_weather()
    assert w == {"available": False, "rain_expected": None, "forecast": None}


# ------------------------------------------------------------------ mandi

def test_mandi_without_api_key_is_unavailable_and_makes_no_request(monkeypatch):
    monkeypatch.setattr(mandi, "DATA_GOV_API_KEY", "")
    monkeypatch.setattr(mandi.requests, "get", boom)  # would fail the test if called and unhandled
    assert mandi.get_mandi_price() == {"available": False}


def test_mandi_parses_first_record(monkeypatch):
    rec = {"market": "Bhatkal", "arrival_date": "21/09/2026", "commodity": "Paddy",
           "variety": "X", "min_price": "2000", "max_price": "2500", "modal_price": "2300"}
    monkeypatch.setattr(mandi, "DATA_GOV_API_KEY", "k")
    monkeypatch.setattr(mandi.requests, "get", lambda *a, **k: FakeResponse(200, {"records": [rec]}))
    m = mandi.get_mandi_price()
    assert m["available"] is True and m["modal_price"] == 2300.0 and m["market"] == "Bhatkal"


@pytest.mark.parametrize("payload", [{"records": []}, {"records": [{"modal_price": ""}]}, {}])
def test_mandi_empty_or_missing_price_is_unavailable(monkeypatch, payload):
    monkeypatch.setattr(mandi, "DATA_GOV_API_KEY", "k")
    monkeypatch.setattr(mandi.requests, "get", lambda *a, **k: FakeResponse(200, payload))
    assert mandi.get_mandi_price() == {"available": False}


def test_mandi_api_failure_is_unavailable(monkeypatch):
    monkeypatch.setattr(mandi, "DATA_GOV_API_KEY", "k")
    monkeypatch.setattr(mandi.requests, "get", boom)
    assert mandi.get_mandi_price() == {"available": False}


# -------------------------------------------------------------------- llm

def test_llm_returns_model_text(monkeypatch):
    data = {"candidates": [{"content": {"parts": [{"text": "  Hello farmer.  "}]}}]}
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: FakeResponse(200, data))
    assert llm.generate_voice_message(["LOW_MOISTURE"]) == "Hello farmer."


def test_llm_prompt_contains_descriptions_but_no_sensor_numbers(monkeypatch):
    seen = {}

    def fake_post(url, json=None, **kw):
        seen["payload"] = json
        return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    llm.generate_voice_message(["LOW_MOISTURE", "SENSOR_FAULT_DHT22"])
    prompt = seen["payload"]["contents"][0]["parts"][0]["text"]
    assert llm.ALERT_CODE_DESCRIPTIONS["LOW_MOISTURE"] in prompt
    assert "SENSOR_FAULT" not in prompt  # codes are translated to prose, not sent raw


@pytest.mark.parametrize("poster", [
    boom,
    lambda *a, **k: FakeResponse(429, {}),
    lambda *a, **k: FakeResponse(200, {"candidates": []}),
])
def test_llm_failure_falls_back_to_deterministic_template(monkeypatch, poster):
    monkeypatch.setattr(llm.requests, "post", poster)
    msg = llm.generate_voice_message(["LOW_MOISTURE"])
    assert msg.startswith("Hello, this is your farm advisory.")
    assert llm.ALERT_CODE_DESCRIPTIONS["LOW_MOISTURE"] in msg


def test_llm_empty_alert_list_returns_empty_and_skips_api(monkeypatch):
    monkeypatch.setattr(llm.requests, "post", boom)
    assert llm.generate_voice_message([]) == ""


def test_every_actionable_code_has_a_description():
    import state_manager
    missing = state_manager.ACTIONABLE_CODES - set(llm.ALERT_CODE_DESCRIPTIONS)
    assert not missing, f"alert codes without a message description: {missing}"


# ------------------------------------------------------------ sms template

def _facts(**kw):
    base = {"soil_moisture_index": 20.0, "temperature_c": 29.5, "humidity_percent": 68.0,
            "light_level": None, "weather_available": True, "rain_expected_next_days": False,
            "mandi": {"available": False}, "rule_version": "v-test"}
    base.update(kw)
    return base


def test_sms_contains_numbers_alerts_and_rule_version():
    sms = message_planner.build_sms_message(["LOW_MOISTURE"], _facts())
    assert "Soil moisture index: 20/100" in sms
    assert "Temperature: 29.5C" in sms
    assert "Humidity: 68%" in sms
    assert "Ambient light" not in sms
    assert "No significant rain expected" in sms
    assert "Rule version: v-test" in sms


def test_sms_weather_unavailable_shown_once():
    sms = message_planner.build_sms_message(
        ["LOW_MOISTURE", "WEATHER_UNAVAILABLE"], _facts(weather_available=False, rain_expected_next_days=None)
    )
    assert sms.count("unavailable") == 1
    assert "temporarily unavailable" not in sms  # the per-code line is skipped


def test_sms_unknown_alert_code_falls_back_to_the_code_itself():
    assert "- SOMETHING_NEW" in message_planner.build_sms_message(["SOMETHING_NEW"], _facts())


# ------------------------------------------------- SMS templates: en / hi / kn

import sms_i18n  # noqa: E402


@pytest.mark.parametrize("lang", ["hi", "kn"])
def test_every_actionable_code_has_a_translation(lang):
    import state_manager
    missing = (state_manager.ACTIONABLE_CODES | {"WEATHER_UNAVAILABLE"}) - set(sms_i18n.ALERTS[lang])
    assert not missing, f"{lang}: alert codes without a translation: {missing}"


def test_every_language_defines_the_same_template_keys():
    reference = set(sms_i18n.STRINGS["en"])
    for lang, table in sms_i18n.STRINGS.items():
        assert set(table) == reference, f"{lang} template keys differ from English"


@pytest.mark.parametrize("lang", ["en", "hi", "kn"])
def test_sms_in_every_language_carries_the_same_numbers(lang):
    sms = message_planner.build_sms_message(["LOW_MOISTURE"], _facts(), lang=lang)
    for expected in ("20/100", "29.5", "68%", "v-test"):
        assert expected in sms


@pytest.mark.parametrize("lang", ["hi", "kn"])
def test_indic_sms_uses_the_translated_alert_text(lang):
    sms = message_planner.build_sms_message(["LOW_MOISTURE"], _facts(), lang=lang)
    assert sms_i18n.ALERTS[lang]["LOW_MOISTURE"] in sms
    assert llm.ALERT_CODE_DESCRIPTIONS["LOW_MOISTURE"] not in sms


def test_indic_sms_unknown_code_falls_back_to_english_then_the_code():
    assert "- SOMETHING_NEW" in message_planner.build_sms_message(["SOMETHING_NEW"], _facts(), lang="kn")


def test_english_sms_is_unchanged_without_a_reading_time():
    sms = message_planner.build_sms_message(["LOW_MOISTURE"], _facts())
    assert sms.startswith("CROP ADVISORY - Paddy\nSoil moisture index: 20/100\n")
    assert "Reading:" not in sms


def test_sms_reading_time_is_formatted_from_the_given_moment():
    from datetime import datetime
    sms = message_planner.build_sms_message(["LOW_MOISTURE"], _facts(), reading_time=datetime(2026, 9, 21, 14, 5))
    assert "Reading: 21-Sep 14:05" in sms.split("\n")[1]


def test_unsupported_language_falls_back_to_english():
    assert sms_i18n.normalize_language("fr") == "en"
    assert sms_i18n.normalize_language(None) == "en"
    assert sms_i18n.normalize_language(" KN ") == "kn"
    assert not sms_i18n.is_supported("fr")
