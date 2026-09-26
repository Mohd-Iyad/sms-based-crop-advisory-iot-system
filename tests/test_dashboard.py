"""
Tests for the /dashboard page (dashboard.py) and the snapshot bookkeeping it
relies on (repositories/devices.py, via state_manager's DB-backed shim).
Everything outbound is mocked.

v3 architecture note: /sensor-data returns 202 immediately; the `post()`
helper below posts AND flushes the delivery queue synchronously
(delivery_queue.process_all_pending()) so every other test in this file can
keep asserting on the dashboard's rendered delivery/SMS state exactly as
before, without each one remembering to flush it individually. Demo endpoints
(/demo/scenario/*) already deliver synchronously and need no such flush.
"""
import os
import sys
from datetime import date, datetime, timedelta
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dashboard
import main
import state_manager
import services.delivery_queue as delivery_queue

KEY = {"X-Device-Key": "test-key"}
FORECAST = [
    {"date": "2026-09-21", "rain_mm": 0.0},
    {"date": "2026-09-22", "rain_mm": 8.0},
    {"date": "2026-09-23", "rain_mm": 1.2},
]


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    client.cookies.clear()          # the dashboard remembers the access key in a cookie: start every test locked
    monkeypatch.setattr(state_manager, "TRANSLATE_SMS_TO", "")   # whatever .env says: default to English
    monkeypatch.setattr(main, "EXPECTED_DEVICE_KEY", "test-key")
    monkeypatch.setattr(main, "SOWING_DATE", (date.today() - timedelta(days=5)).isoformat())
    monkeypatch.setattr(main, "ENABLE_VOICE_CALL", False)
    monkeypatch.setattr(delivery_queue, "ENABLE_VOICE_CALL", False)
    monkeypatch.setattr(state_manager, "ALERT_COOLDOWN_MINUTES", 720)

    monkeypatch.setattr(delivery_queue, "send_sms", lambda m, **_: {"success": True, "status_code": 201})
    weather_ok = lambda: {"available": True, "rain_expected": True, "forecast": FORECAST}
    mandi_off = lambda: {"available": False}
    monkeypatch.setattr(delivery_queue, "get_weather", weather_ok)
    monkeypatch.setattr(delivery_queue, "get_mandi_price", mandi_off)
    monkeypatch.setattr(main, "get_weather", weather_ok)
    monkeypatch.setattr(main, "get_mandi_price", mandi_off)
    yield


client = TestClient(main.app)


def post(seq, moisture=50.0, device="FIELD-001", **kw):
    body = {"device_id": device, "sequence": seq, "soil_moisture": moisture,
            "temperature": 28.0, "humidity": 60.0, "raining": False}
    body.update(kw)
    r = client.post("/sensor-data", json=body, headers=KEY)
    assert r.status_code == 202
    delivery_queue.process_all_pending()
    return r.json()


def page(path="/dashboard"):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    return r.text


# ------------------------------------------------------------- empty state

def test_empty_state_explains_what_to_do():
    html = page()
    assert "Waiting for the first sensor reading" in html
    assert "Power on the field node" in html
    assert "/sensor-data-preview" not in html              # no developer endpoints in user-facing text


def test_preview_does_not_populate_the_dashboard():
    client.post("/sensor-data-preview", json={"device_id": "X", "sequence": 1, "soil_moisture": 20})
    assert "Waiting for the first sensor reading" in page()


# --------------------------------------------------------- rendering states

def test_dry_field_shows_attention_and_readable_alert():
    post(1, 20, light_level=61)
    html = page()
    assert "Attention needed" in html
    assert "The soil moisture is low." in html          # human-readable text ...
    assert "<code>LOW_MOISTURE</code>" in html          # ... with the raw code kept for reference
    assert 'class="tag warn"' in html and ">Low<" in html
    assert 'aria-valuenow="20"' in html and "left:20.0%" in html
    assert "Day 5" in html
    assert "FIELD-001" in html
    assert "61" in html


def test_healthy_field_is_all_clear():
    post(1, 50)
    html = page()
    assert "All clear" in html
    assert "No active alerts." in html
    assert ">Normal<" in html


def test_waterlogged_field():
    post(1, 90)
    html = page()
    assert "Attention needed" in html and ">Too wet<" in html
    assert "high moisture" in html


def test_gauge_uses_agronomy_thresholds_and_clamps():
    post(1, 100)
    html = page()
    assert "var(--warn) 0 28.0%" in html and "var(--wet) 75.0% 100%" in html
    assert "left:100.0%" in html


def test_sensor_fault_is_shown_honestly_not_faked():
    post(1, 55, temperature=None, humidity=None)
    html = page()
    assert "Sensor fault" in html
    assert "DHT22 sensor not responding" in html
    assert 'class="na">N/A' in html
    assert "SENSOR_FAULT_DHT22" in html


def test_missing_soil_sensor():
    post(1, None)
    html = page()
    assert "The soil moisture sensor is not reporting." in html
    assert "SENSOR_FAULT_SOIL" in html


def test_faults_sort_before_warnings():
    post(1, 20, temperature=None, humidity=None)
    html = page()
    assert html.index("SENSOR_FAULT_DHT22") < html.index("<code>LOW_MOISTURE</code>")


# ----------------------------------------------------- weather: two distinct states

def test_forecast_shown_when_it_was_fetched():
    post(1, 20)
    html = page()
    assert "Rain forecast (3 days)" in html
    assert "Rain expected" in html
    assert "8.0 mm" in html and 'class="heavy"' in html   # >= 5 mm is flagged
    assert "Tue 22 Sep" in html


def test_not_checked_is_not_reported_as_unavailable():
    """Regression: a reading with no new alert never fetches weather; that is not an outage."""
    post(1, 20)                     # alert -> weather fetched
    post(2, 19, temperature=30.0)   # same alert, cooldown -> weather NOT fetched
    html = page()
    assert "Not checked" in html
    assert "Unavailable" not in html
    assert "WEATHER_UNAVAILABLE" not in html


def test_real_weather_outage_is_reported_as_unavailable_not_no_rain(monkeypatch):
    monkeypatch.setattr(delivery_queue, "get_weather", lambda: {"available": False, "rain_expected": None, "forecast": None})
    post(1, 20)
    html = page()
    assert "Unavailable" in html
    assert "does not mean no rain" in html
    assert "No significant rain" not in html
    assert "WEATHER_UNAVAILABLE" in html   # a genuine outage is still listed


def test_mandi_card_when_available(monkeypatch):
    monkeypatch.setattr(delivery_queue, "get_mandi_price", lambda: {
        "available": True, "market": "Bhatkal", "arrival_date": "21/09/2026",
        "modal_price": 2300.0, "min_price": "2100", "max_price": "2500"})
    post(1, 20)
    html = page()
    assert "Mandi price" in html and "Rs 2,300" in html and "range Rs 2100 to 2500" in html


def test_no_mandi_card_without_a_price():
    post(1, 20)
    assert "Mandi price" not in page()


# --------------------------------------------------------------- delivery

def test_delivery_status_shown_after_an_alert():
    post(1, 20)
    html = page()
    assert "Last advisory sent" in html
    assert 'class="tag ok" style="margin:0">sent<' in html
    assert "disabled (SMS-only mode)" in html


def test_delivery_status_survives_the_next_healthy_reading():
    """Regression: the panel used to vanish as soon as a reading sent nothing."""
    post(1, 20)
    post(2, 50)
    html = page()
    assert 'class="tag ok" style="margin:0">sent<' in html


def test_failed_delivery_is_flagged(monkeypatch):
    monkeypatch.setattr(delivery_queue, "send_sms", lambda m, **_: {"success": False, "error": "textbee 401: bad key", "retryable": False})
    post(1, 20)
    html = page()
    assert 'class="tag bad" style="margin:0">failed: textbee 401: bad key<' in html


def test_no_delivery_yet_message():
    post(1, 50)
    assert "No advisory has been sent yet" in page()


# ------------------------------------------------------------ multi-device

def test_device_switcher_and_selection():
    post(1, 20, device="FIELD-A")
    post(1, 50, device="FIELD-B")
    both = page()
    assert 'href="?device=FIELD-A"' in both and 'href="?device=FIELD-B"' in both
    assert both.count(' aria-current="page"') == 1      # leading space: not the CSS selector

    b = page("/dashboard?device=FIELD-B")
    assert "All clear" in b
    # The manual "Refresh" link can share the exact same href text as the
    # device-switcher link when no ?key= is present, so target the <nav> block
    # specifically rather than the first matching href anywhere on the page.
    nav = b.split('class="devices"')[1]
    assert ' aria-current="page"' in nav.split('href="?device=FIELD-B"')[1][:40]
    a = page("/dashboard?device=FIELD-A")
    assert "Attention needed" in a


def test_single_device_shows_no_switcher():
    post(1, 50)
    assert 'class="devices"' not in page()


def test_unknown_device_falls_back_and_creates_no_state():
    post(1, 50, device="FIELD-A")
    before = list(state_manager.get_all_device_ids())
    html = page("/dashboard?device=nope")
    assert "No device called" in html and "nope" in html
    assert "FIELD-A" in html
    assert state_manager.get_all_device_ids() == before   # a lookup must not create state


# -------------------------------------------------------------- staleness

def test_stale_device_is_flagged():
    post(1, 50)
    later = datetime.now() + timedelta(minutes=20)
    html = dashboard.render_dashboard(now=later)
    assert "No recent data" in html
    assert 'class="live off"' in html
    assert "All clear" not in html


def test_recent_device_is_not_stale():
    post(1, 50)
    html = dashboard.render_dashboard(now=datetime.now() + timedelta(seconds=90))
    assert "No recent data" not in html
    assert "1 min ago" in html
    assert 'class="grid stale"' not in html


def test_device_silent_for_a_few_minutes_is_flagged_and_dimmed():
    """The ESP32 reports every 15 s: three silent minutes must not still read 'All clear'."""
    post(1, 50)
    html = dashboard.render_dashboard(now=datetime.now() + timedelta(minutes=3))
    assert "No recent data" in html
    assert 'class="grid stale"' in html                    # the old numbers are dimmed, not shown as live
    assert 'class="live off"' in html                      # ...and the top-bar indicator agrees


# ---------------------------------------------------- security / robustness

def test_hostile_device_id_is_escaped():
    evil = "<script>alert(1)</script>"
    post(1, 50, device=evil)
    post(1, 50, device="FIELD-B")
    for path in ("/dashboard", "/dashboard?device=%3Cscript%3Ealert%281%29%3C%2Fscript%3E"):
        html = page(path)
        assert "<script>alert(1)" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_hostile_query_param_is_escaped():
    post(1, 50)
    html = page("/dashboard?device=%3Cimg%20src%3Dx%20onerror%3Dalert(1)%3E")
    assert "<img src=x" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_snapshot_with_missing_fields_does_not_crash():
    """Old / partial snapshots (no facts, no timestamp) must still render."""
    state_manager.set_test_snapshot("LEGACY", facts={}, alert_codes=[])
    html = page()
    assert "LEGACY" in html and "All clear" in html


def test_unknown_alert_code_still_renders():
    state_manager.set_test_snapshot("D", facts={}, alert_codes=["BRAND_NEW_CODE"])
    assert "BRAND_NEW_CODE" in page()


class _Balanced(HTMLParser):
    VOID = {"meta", "br", "img", "input", "link", "hr"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}> (open: {self.stack[-3:]})")
        else:
            self.stack.pop()


@pytest.mark.parametrize("scenario", ["empty", "dry", "healthy", "fault", "two_devices"])
def test_html_is_well_formed(scenario):
    if scenario == "dry":
        post(1, 20)
    elif scenario == "healthy":
        post(1, 50)
    elif scenario == "fault":
        post(1, None, temperature=None, humidity=None)
    elif scenario == "two_devices":
        post(1, 20, device="A")
        post(1, 50, device="B")
    parser = _Balanced()
    parser.feed(page())
    assert parser.errors == [] and parser.stack == []


# -------------------------------------------------------------- stage text

@pytest.mark.parametrize("days,expected", [
    (5, "Next: tillering fertilizer window opens in 13 days (day 18)"),
    (20, "Tillering fertilizer window is open now (until day 25)"),
    (30, "Next: panicle fertilizer window opens in 10 days (day 40)"),
    (45, "Panicle fertilizer window is open now (until day 50)"),
    (60, "About 55 days until the estimated harvest check."),
    (108, "Harvest window approaching: about 7 days to go."),
    (114, "Harvest window approaching: about 1 day to go."),
    (115, "Estimated maturity reached."),
    (140, "Estimated maturity reached."),
])
def test_stage_summary(days, expected):
    assert dashboard._stage_summary(days, 115).startswith(expected)


# ------------------------------------------------------- snapshot bookkeeping

def test_snapshot_is_timestamped():
    state_manager.set_test_snapshot("D", facts={}, alert_codes=[])
    snap = state_manager.get_snapshot("D")
    assert datetime.fromisoformat(snap["updated_at"]) <= datetime.now()


def test_snapshot_keeps_last_delivery_until_a_new_one_replaces_it():
    d1 = {"sms_status": "sent", "voice_status": "disabled"}
    state_manager.set_test_snapshot("D", facts={}, alert_codes=[], delivery=d1)
    first = state_manager.get_snapshot("D")["delivery_at"]

    state_manager.set_test_snapshot("D", facts={}, alert_codes=[])      # nothing sent this time
    snap = state_manager.get_snapshot("D")
    assert snap["delivery"] == d1 and snap["delivery_at"] == first

    d2 = {"sms_status": "failed: x", "voice_status": "disabled"}
    state_manager.set_test_snapshot("D", facts={}, alert_codes=[], delivery=d2)
    assert state_manager.get_snapshot("D")["delivery"] == d2


# ------------------------------------------- demo panel, language chips, SMS banner

def test_locked_panel_offers_a_link_to_the_key_box_not_url_instructions():
    post(1, 50)
    html = page()
    assert 'href="?unlock=1&amp;device=FIELD-001#demo-controls"' in html
    assert 'name="key"' not in html                       # the input only exists on the no-refresh page
    assert 'action="/demo/scenario/' not in html          # no send buttons without the key
    assert "/settings/sms-language" not in html           # language chips are read-only when locked


def test_unlock_page_shows_the_key_box_and_does_not_auto_refresh():
    """A reload every 15 s would wipe a key half-typed into the box."""
    post(1, 50)
    html = page("/dashboard?unlock=1&device=FIELD-001")
    assert 'name="key"' in html and "Unlock" in html
    assert 'name="device" value="FIELD-001"' in html
    assert 'http-equiv="refresh"' not in html


def test_normal_pages_do_auto_refresh():
    post(1, 50)
    assert 'http-equiv="refresh"' in page()
    assert 'http-equiv="refresh"' in page("/dashboard?key=test-key")


def test_unlocked_page_ignores_the_unlock_flag():
    post(1, 50)
    html = page("/dashboard?key=test-key&unlock=1")
    assert 'name="key"' not in html and 'action="/demo/scenario/' in html
    assert 'http-equiv="refresh"' in html


def test_unlocked_panel_posts_back_to_the_dashboard_with_the_viewed_device():
    post(1, 50)
    html = page("/dashboard?key=test-key")
    # once unlocked the key is remembered in a cookie: it is never put into the buttons' URLs
    assert 'action="/demo/scenario/sensor_fault_dht?back=dashboard"' in html
    assert 'action="/settings/sms-language?lang=kn&amp;back=dashboard&amp;device=FIELD-001"' in html
    assert "test-key" not in html
    assert 'name="key"' not in html                       # unlocked: no unlock box


def test_language_chips_highlight_the_current_language():
    post(1, 50)
    assert page("/dashboard?key=test-key").count('class="lang-chip active"') == 1
    state_manager.set_sms_language("kn")
    html = page("/dashboard?key=test-key")
    assert 'class="lang-chip active" lang="kn"' in html
    assert 'class="lang-chip active" lang="en"' not in html


def test_banner_confirms_a_sent_sms_with_its_text():
    client.post("/demo/scenario/sensor_fault_dht", headers=KEY)
    html = page()
    assert "SMS sent" in html and 'class="sms-banner ok"' in html
    assert "<details>" in html and "<details open>" not in html  # collapsed by default, expands on click
    assert "temperature and humidity sensor" in html       # the SMS body is in the markup either way
    assert "[TEST]" in html                                # demo SMS are marked as such


def test_banner_flags_a_failed_sms(monkeypatch):
    monkeypatch.setattr(delivery_queue, "send_sms", lambda m, **_: {"success": False, "error": "textbee 401: bad key", "retryable": False})
    client.post("/demo/scenario/sensor_fault_dht", headers=KEY)
    html = page()
    assert 'class="sms-banner bad"' in html
    assert "SMS FAILED" in html and "textbee 401: bad key" in html


def test_banner_is_absent_before_any_sms():
    post(1, 50)
    assert "sms-banner" not in page().split("</style>")[1]


def test_banner_escapes_hostile_content(monkeypatch):
    monkeypatch.setattr(delivery_queue, "send_sms", lambda m, **_: {"success": False, "error": "<script>alert(1)</script>", "retryable": False})
    client.post("/demo/scenario/sensor_fault_dht", headers=KEY)
    html = page()
    assert "<script>alert(1)</script>" not in html


def test_default_device_is_the_live_one_not_a_demo_device():
    client.post("/demo/scenario/low_moisture", headers=KEY)        # creates DEMO-LOW_MOISTURE first
    post(1, 50, device="FIELD-001")
    html = page()
    assert "Device: FIELD-001" in html and "Device: DEMO-LOW_MOISTURE" not in html


def test_default_device_is_the_most_recently_updated_real_device():
    post(1, 50, device="FIELD-A")
    post(1, 50, device="FIELD-B")
    post(2, 50, device="FIELD-A")
    assert "Device: FIELD-A" in page()


def test_demo_device_is_shown_when_it_is_the_only_one():
    client.post("/demo/scenario/low_moisture", headers=KEY)
    assert "Device: DEMO-LOW_MOISTURE" in page()


# ------------------------------------------------------------- wrong device key

def test_wrong_key_in_the_url_does_not_unlock_and_says_so():
    post(1, 50)
    html = page("/dashboard?key=FIELD-001")                # the device NAME, not the secret key
    assert "Incorrect access key" in html
    assert 'name="key"' in html                            # still locked: the key box is shown again
    assert 'action="/demo/scenario/' not in html
    assert "key=FIELD-001" not in html                     # the wrong key is not carried around in links
    assert 'http-equiv="refresh"' not in html              # so a retry isn't wiped by a reload


def test_correct_key_shows_no_error():
    post(1, 50)
    html = page("/dashboard?key=test-key")
    assert "Incorrect access key" not in html
    assert 'action="/demo/scenario/' in html


def test_error_param_from_a_rejected_button_shows_the_notice():
    post(1, 50)
    html = page("/dashboard?device=FIELD-001&error=key")
    assert "Incorrect access key" in html and 'name="key"' in html


def test_key_error_notice_coexists_with_the_unknown_device_notice():
    post(1, 50)
    html = page("/dashboard?device=nope&error=key")
    assert "Incorrect access key" in html and "No device called" in html


# ------------------------------------------------ polish: switcher, header, indicator, wording

def test_demo_devices_stay_out_of_the_switcher_unless_one_is_open():
    post(1, 50, device="FIELD-001")
    client.post("/demo/scenario/low_moisture", headers=KEY)
    client.post("/demo/scenario/sensor_fault_dht", headers=KEY)
    assert 'class="devices"' not in page()                        # one real device: no switcher at all
    demo_view = page("/dashboard?device=DEMO-LOW_MOISTURE")
    assert 'class="devices"' not in demo_view                     # a simulated page has "Back to real values" instead
    assert "Back to real values" in demo_view


def test_header_uses_the_configured_location_and_crop(monkeypatch):
    monkeypatch.setattr(dashboard, "LOCATION_NAME", "Sirsi <b>")
    post(1, 50)
    html = page()
    assert "Sirsi &lt;b&gt; &middot; Paddy" in html               # configured, capitalised crop, escaped
    assert "Bhatkal &middot; Paddy" not in html


@pytest.mark.parametrize("moisture, dot, label", [
    (50, 'class="live"', "All clear"),
    (15, 'class="live warn"', "Attention needed"),
])
def test_top_bar_indicator_follows_the_field_status(moisture, dot, label):
    post(1, moisture)
    html = page()
    bar = html.split('class="topbar-meta"')[1].split("</div>")[0]
    assert dot in bar and label in bar


def test_top_bar_indicator_is_red_on_a_sensor_fault_and_grey_when_stale():
    post(1, 50, temperature=None, humidity=None)
    assert 'class="live bad"' in page().split('class="topbar-meta"')[1].split("</div>")[0]
    stale = dashboard.render_dashboard(now=datetime.now() + timedelta(minutes=10))
    assert 'class="live off"' in stale.split('class="topbar-meta"')[1].split("</div>")[0]


def test_top_bar_says_waiting_before_the_first_reading():
    bar = page().split('class="topbar-meta"')[1].split("</div>")[0]
    assert "Waiting for data" in bar and 'class="live off"' in bar


@pytest.mark.parametrize("seconds, text", [
    (0, "just now"), (9, "just now"), (10, "10 s ago"), (45, "45 s ago"),
    (60, "1 min ago"), (3600, "1 h ago"), (3 * 86400, "3 d ago"),
])
def test_ago_wording(seconds, text):
    assert dashboard._ago(seconds) == text


def test_no_developer_wording_on_the_locked_panel():
    post(1, 50)
    html = page().split('id="demo-controls"')[1]
    for word in ("EXPECTED_DEVICE_KEY", ".env", "config.h"):
        assert word not in html


def test_css_keeps_the_polish_rules_that_fix_contrast_and_wrapping():
    css = dashboard.CSS
    for rule in (".heavy { color:#9a5b00; }", "overflow-wrap:anywhere", "Noto Sans Kannada", "button, input { font-family:inherit; }"):
        assert rule in css


# ------------------------------------------- introduce a problem / back to real values / remember the key

def test_the_page_has_no_side_panel():
    post(1, 50)
    body = page().split("</style>")[1]                     # the markup, not the stylesheet
    assert "<aside" not in body and 'class="rail' not in body and "FIELD VIEW" not in body


def test_locked_controls_offer_the_key_box_and_sit_above_the_readings():
    post(1, 50)
    html = page()
    assert "Enter access key" in html
    assert html.index('id="demo-controls"') < html.index('class="status')


def test_entering_the_right_key_unlocks_once_and_keeps_the_key_out_of_the_url():
    post(1, 50)
    r = client.get("/dashboard?key=test-key&device=FIELD-001", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/dashboard?device=FIELD-001"
    assert "advisory_key=test-key" in r.headers["set-cookie"]
    assert "HttpOnly" in r.headers["set-cookie"] and "SameSite=strict" in r.headers["set-cookie"]
    html = page()                                           # a later plain visit: still unlocked (cookie)
    assert 'action="/demo/scenario/low_moisture?back=dashboard"' in html and "Enter access key" not in html


def test_a_wrong_key_sets_no_cookie_and_stays_locked():
    post(1, 50)
    r = client.get("/dashboard?key=nope", follow_redirects=False)
    assert r.status_code == 200 and "set-cookie" not in r.headers
    assert "Incorrect access key" in r.text and 'action="/demo/scenario/' not in r.text


def test_lock_forgets_the_key():
    post(1, 50)
    client.get("/dashboard?key=test-key")
    assert 'action="/demo/scenario/' in page()
    r = client.post("/dashboard/lock", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/dashboard"
    html = page()
    assert 'action="/demo/scenario/' not in html and "Enter access key" in html


def test_a_forged_or_stale_cookie_does_not_unlock():
    post(1, 50)
    client.cookies.set("advisory_key", "not-the-key")
    assert 'action="/demo/scenario/' not in page()
    assert client.post("/demo/scenario/low_moisture").status_code == 401


def test_the_unlocked_panel_lists_every_problem_plus_back_to_real_values_and_lock():
    post(1, 50)
    client.get("/dashboard?key=test-key")
    html = page()
    for title in ("DHT22 sensor fault", "Low soil moisture", "Harvest check due"):
        assert title in html
    assert 'action="/demo/reset?back=dashboard"' in html and "Back to real values" in html
    assert 'action="/dashboard/lock"' in html


def test_introducing_a_problem_shows_it_and_says_so():
    post(1, 50)                                             # the real field is fine
    client.get("/dashboard?key=test-key")
    html = client.post("/demo/scenario/low_moisture?back=dashboard").text     # follows the redirect
    assert "Problem introduced: Low soil moisture" in html and "SMS sent" in html
    assert "Simulated problem" in html and "not from the field sensor" in html
    assert "Attention needed" in html and "LOW_MOISTURE" in html      # the problem is visible on the page
    assert "[TEST]" in html
    assert 'class="pill primary"' in html                             # "Back to real values" is emphasised
    assert "No recent data" not in html and "Last update" not in html # simulated readings never look stale


def test_a_failed_introduced_problem_says_the_sms_failed(monkeypatch):
    monkeypatch.setattr(delivery_queue, "send_sms", lambda m, **_: {"success": False, "error": "textbee 401: bad key", "retryable": False})
    client.get("/dashboard?key=test-key")
    html = client.post("/demo/scenario/low_moisture?back=dashboard").text
    assert "Problem introduced: Low soil moisture" in html
    assert "SMS FAILED" in html and "textbee 401: bad key" in html and 'class="sms-banner bad"' in html


def test_a_simulated_page_is_never_marked_stale():
    client.post("/demo/scenario/low_moisture", headers=KEY)
    html = dashboard.render_dashboard("DEMO-LOW_MOISTURE", now=datetime.now() + timedelta(minutes=30))
    assert "No recent data" not in html and "Attention needed" in html


def test_back_to_real_values_returns_to_the_real_field_and_clears_the_simulation():
    post(1, 50)
    client.get("/dashboard?key=test-key")
    client.post("/demo/scenario/low_moisture?back=dashboard")
    assert "DEMO-LOW_MOISTURE" in state_manager.get_all_device_ids()
    html = client.post("/demo/reset?back=dashboard").text              # ...and follows the redirect
    assert "Simulated problem" not in html and "Problem introduced" not in html
    assert "All clear" in html and "Device: FIELD-001" in html          # the real values are back
    assert "DEMO-LOW_MOISTURE" not in state_manager.get_all_device_ids()
    assert state_manager.get_last_sms_event() is None                   # the demo notification is gone


def test_reset_clears_only_the_simulated_notification_and_devices():
    """
    v3: the banner is derived from delivery history (DB-backed, survives a
    restart), not a single in-memory slot -- so clearing the simulated event
    reveals the last REAL one underneath it, rather than going blank. That's
    an improvement over the old single-slot behaviour (an operator who reset
    a demo would otherwise lose visibility into their real device's last
    confirmed SMS for no reason).
    """
    post(1, 20)                                                        # a REAL low-moisture SMS goes out
    client.get("/dashboard?key=test-key")
    client.post("/demo/scenario/sensor_fault_dht?back=dashboard")      # then a simulated one
    assert state_manager.get_last_sms_event()["simulated"] is True
    client.post("/demo/reset?back=dashboard")
    event = state_manager.get_last_sms_event()
    assert event is not None and event["simulated"] is False           # the real event is visible again
    assert "FIELD-001" in state_manager.get_all_device_ids()           # the real device stays


def test_reset_keeps_a_real_notification():
    client.get("/dashboard?key=test-key")
    post(1, 20)                                                        # a real SMS is the latest event
    client.post("/demo/reset?back=dashboard")
    event = state_manager.get_last_sms_event()
    assert event is not None and event["simulated"] is False           # nothing simulated to clear


def test_reset_needs_the_key():
    assert client.post("/demo/reset").status_code == 401
    r = client.post("/demo/reset?back=dashboard&key=nope", follow_redirects=False)
    assert r.status_code == 303 and "error=key" in r.headers["location"]


def test_locked_viewer_of_a_simulated_page_gets_a_plain_back_link():
    client.post("/demo/scenario/low_moisture", headers=KEY)
    html = page("/dashboard?device=DEMO-LOW_MOISTURE")
    assert 'href="/dashboard">Back to real values' in html


def test_dashboard_is_open_when_no_key_is_configured(monkeypatch):
    monkeypatch.setattr(main, "EXPECTED_DEVICE_KEY", "")
    post(1, 50)
    html = page()
    assert 'action="/demo/scenario/low_moisture?back=dashboard"' in html and "Enter access key" not in html
