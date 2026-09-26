"""
Loads all secrets/config from environment variables.
Locally these come from a .env file (via python-dotenv).
On Render, these come from the Environment Variables you set in the dashboard.

SECURITY NOTE: this file must contain zero hardcoded credentials or API
keys -- every real value comes from .env (which is gitignored) or Render's
environment settings. If a key is missing, the relevant feature degrades
gracefully (see weather.py / mandi.py) rather than the app crashing.
"""
import os
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()  # reads .env file if present (does nothing on Render, which is fine)

# Hosting platforms (e.g. Render) run in UTC. The SMS "Reading:" time, the crop-age
# calculation and the "did it rain in the last 6 h" check all use local time, so pin
# it to India time unless the operator chose one. (time.tzset exists on Linux/macOS
# only; on Windows the PC's own clock is used, so nothing is changed there.)
if hasattr(time, "tzset") and not os.getenv("TZ"):
    os.environ["TZ"] = "Asia/Kolkata"
    time.tzset()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
TWILIO_TO_NUMBER = os.getenv("TWILIO_TO_NUMBER", "")  # your verified personal number

# Which SMS provider to actually use: "twilio" (default) or "textbee".
# textbee (https://textbee.dev) turns an Android phone into the SMS sender
# using its own SIM/carrier plan -- no trial-template restriction, no
# per-message cost, no DLT registration needed for this kind of low-volume
# personal/prototype use. Switching providers needs zero code changes.
SMS_PROVIDER = os.getenv("SMS_PROVIDER", "twilio").lower()
TEXTBEE_API_KEY = os.getenv("TEXTBEE_API_KEY", "")
TEXTBEE_DEVICE_ID = os.getenv("TEXTBEE_DEVICE_ID", "")  # optional; blank uses your default registered device

# The number that actually receives the advisory, regardless of provider.
# Falls back to TWILIO_TO_NUMBER if not set separately, so your existing
# .env keeps working with zero changes even if you only set that one.
ADVISORY_TO_NUMBER = os.getenv("ADVISORY_TO_NUMBER", "").strip() or TWILIO_TO_NUMBER

# v5: a farmer's household often wants more than one phone reached -- the
# farmer themself plus, say, a son working elsewhere who manages the field
# remotely. ADVISORY_TO_NUMBERS takes a comma-separated list and fans out one
# delivery job per recipient (each with its own independent retry/backoff, so
# one bad number never blocks the others). If unset, this list is just
# [ADVISORY_TO_NUMBER], so a single-recipient .env keeps working unchanged.
_extra_numbers = [n.strip() for n in os.getenv("ADVISORY_TO_NUMBERS", "").split(",") if n.strip()]
ADVISORY_RECIPIENTS = _extra_numbers or ([ADVISORY_TO_NUMBER] if ADVISORY_TO_NUMBER else [])

# Voice + language for the phone call. Defaults to an English Indian voice.
# For a Kannada demo, switch to a supported Google Kannada voice, e.g.:
#   TWILIO_VOICE=Google.kn-IN-Standard-A
#   TWILIO_VOICE_LANGUAGE=kn-IN
# Note: Polly.Aditi (the previous default) is bilingual Hindi/Indian-English
# ONLY -- it is not a Kannada voice, so it must not be used for Kannada text.
TWILIO_VOICE = os.getenv("TWILIO_VOICE", "Polly.Aditi")
TWILIO_VOICE_LANGUAGE = os.getenv("TWILIO_VOICE_LANGUAGE", "en-IN")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# No hardcoded fallback key -- if this is missing, mandi.py returns
# "unavailable" instead of silently using a shared public key from source code.
DATA_GOV_API_KEY = os.getenv("DATA_GOV_API_KEY", "")

# Simple shared-secret header check so random internet requests can't trigger
# your phone. Not real security, just enough to stop accidental/abusive hits.
EXPECTED_DEVICE_KEY = os.getenv("EXPECTED_DEVICE_KEY", "")

# Location settings for Bhatkal, Karnataka (used for weather + mandi lookups)
LOCATION_NAME = os.getenv("LOCATION_NAME", "Bhatkal")
LOCATION_LAT = float(os.getenv("LOCATION_LAT", "13.9853"))
LOCATION_LON = float(os.getenv("LOCATION_LON", "74.5550"))
MANDI_STATE = os.getenv("MANDI_STATE", "Karnataka")
MANDI_DISTRICT = os.getenv("MANDI_DISTRICT", "Uttara Kannada")
MANDI_COMMODITY = os.getenv("MANDI_COMMODITY", "Paddy")

# Sowing date lives on the BACKEND now, not the firmware -- the ESP32 no
# longer needs NTP time sync just to compute days-since-sowing. Format: YYYY-MM-DD
SOWING_DATE = os.getenv("SOWING_DATE", "2026-06-15")

# Fail fast, with a message that says what to fix. A malformed date would otherwise
# only surface later as an unhandled 500 on every single sensor reading.
try:
    datetime.strptime(SOWING_DATE, "%Y-%m-%d")
except ValueError:
    raise RuntimeError(
        f"SOWING_DATE must be in YYYY-MM-DD format (e.g. 2026-06-15), got {SOWING_DATE!r}. "
        "Fix it in your .env file."
    ) from None

# SMS timing. A NEW condition (or an error) is always sent immediately. While the
# same condition keeps being true it is repeated every ALERT_COOLDOWN_MINUTES
# (moisture, sensor faults, rain warning). A healthy field sends nothing.
#
# v5: the default is now 360 minutes (6 hours) -- a real farmer does not want
# a repeat "soil still dry" text every 5 minutes; 4 updates a day (roughly
# dawn / mid-morning / afternoon / evening) is the cadence actually asked for
# in real deployments and keeps SMS cost and phone-buzzing sane. For a stage
# demo where you want to see repeats quickly, override it in .env:
#   ALERT_COOLDOWN_MINUTES=5
ALERT_COOLDOWN_MINUTES = int(os.getenv("ALERT_COOLDOWN_MINUTES", "360"))

# Fertilizer and harvest reminders depend only on the calendar and stay true for
# days (HARVEST_CHECK_DUE for good), so they repeat far less often than the above --
# otherwise a healthy field would be texted every few minutes forever.
TIME_BASED_ALERT_COOLDOWN_MINUTES = int(os.getenv("TIME_BASED_ALERT_COOLDOWN_MINUTES", "1440"))  # 24 h

# The dashboard calls a device "No recent data" when nothing has arrived for this
# many minutes. The ESP32 reports every 15 seconds; raise this if you raise its interval.
STALE_AFTER_MINUTES = float(os.getenv("STALE_AFTER_MINUTES", "2"))

# Set to "true" when the server is reachable from the internet (a domain). It then
# refuses to start with a weak/empty EXPECTED_DEVICE_KEY, hides /docs, and requires
# the key on /sensor-data-preview. Leave off for a prototype on your own Wi-Fi.
PUBLIC_MODE = os.getenv("PUBLIC_MODE", "false").strip().lower() == "true"

# Voice calling is fully implemented (see telephony.py + llm.py) but disabled
# by default -- SMS alone is simpler to demo reliably and avoids voice/
# language-quality risk on stage. Set to "true" to re-enable it; no code
# changes needed. When disabled, the Gemini call for voice-message
# generation is skipped entirely too, not just the phone call.
ENABLE_VOICE_CALL = os.getenv("ENABLE_VOICE_CALL", "false").lower() == "true"

# Default language of the SMS: "en" (English, also used when blank), "hi"
# (Hindi) or "kn" (Kannada). The wording comes from built-in templates
# (sms_i18n.py) -- nothing is machine-translated. The dashboard can override
# this at runtime (SMS language chips); that choice lasts until the server
# restarts, after which this value is used again.
TRANSLATE_SMS_TO = os.getenv("TRANSLATE_SMS_TO", "").strip().lower()

# ---------------------------------------------------------------------------
# Persistence + delivery worker (v3). SQLite locally, swappable to Postgres
# for a hosted deployment (e.g. postgresql+psycopg://...) without touching
# any repository/service code -- see database.py.
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./crop_advisory.db")

# How many times a delivery job is attempted before it is marked
# failed_permanent and given up on (see services/delivery_queue.py).
SMS_RETRY_MAX_ATTEMPTS = int(os.getenv("SMS_RETRY_MAX_ATTEMPTS", "5"))

# Fixed backoff between delivery attempts (seconds), capped at the last value.
# attempt 1 fails -> wait 30s -> attempt 2 fails -> wait 60s -> ... -> 900s cap.
SMS_RETRY_BACKOFF_SECONDS = [30, 60, 120, 300, 900]

# How often the background delivery worker thread polls for due jobs.
WORKER_POLL_INTERVAL_SECONDS = float(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "2"))

# Starts the background delivery worker thread. Tests set this to "false"
# (see tests/conftest.py) so delivery only happens when a test explicitly
# calls services.delivery_queue.process_all_pending() -- deterministic,
# no timing-dependent assertions.
ENABLE_DELIVERY_WORKER = os.getenv("ENABLE_DELIVERY_WORKER", "true").strip().lower() == "true"
