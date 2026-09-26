# Crop Advisory Backend — v5 Upgrade Guide

This is a co-authored continuation of the Voice-First Crop Advisory System
built for the ESP32 + LLM + Twilio paddy-advisory project (Bhatkal,
Karnataka). It picks up from v4 and closes the gap between "settings tuned
for a demo" and "settings that make sense for a real field."

If you already know how to run v4, skip to **What actually changed** below.
If you're setting this up for the first time, follow **Setup** in order.

---

## What actually changed in v5

### 1. Multi-recipient delivery (real feature, not cosmetic)

**Before:** one `ADVISORY_TO_NUMBER`. The delivery job even *stored* a
`recipient` field per job, but the actual send to Twilio/textbee ignored it
and always used the single hardcoded number — so the multi-recipient schema
existed but silently did nothing.

**Now:**
- `config.py` reads `ADVISORY_TO_NUMBERS` (comma-separated). If set, it
  replaces the single-number behavior entirely.
- `telephony.send_sms()` and `telephony.make_voice_call()` take an explicit
  `to=` argument.
- `services/delivery_queue.py` creates one `DeliveryJob` **per recipient**
  and passes each job's own `recipient` through to the actual send — so
  every configured number really does get messaged, each with its own
  independent retry/backoff (a bad number for one household member never
  blocks or delays delivery to another).

Set it in `.env`:
```
ADVISORY_TO_NUMBERS=+919876543210,+919812345678
```
Leave it blank and `ADVISORY_TO_NUMBER` (singular) keeps working exactly as
before — nothing breaks for a single-recipient setup.

### 2. Real-world alert cadence, not demo cadence

**Before:** `ALERT_COOLDOWN_MINUTES=5` — fine for showing repeats live on
stage, useless for an actual field (a farmer does not want a "soil still
dry" text every 5 minutes for hours).

**Now:** default is `360` (6 hours ≈ 4 updates a day). A brand-new
condition or an error is still texted immediately, exactly as before — this
only changes how often an *unchanged* condition repeats.

For a live demo where you want to see a repeat quickly, override it back:
```
ALERT_COOLDOWN_MINUTES=5
```

### 3. Dashboard refresh

The dark theme's accent color moved from purple to teal, and the page title
now reads "Crop Advisory v5." Cosmetic only — no functional change.

### 4. Test suite

All 289 existing tests pass against v5 unchanged in behavior (the fakes for
`send_sms`/`make_voice_call` were updated to accept the new `to=` keyword
argument; that's the only test-side change).

---

## Setup (from zero)

### Step 1 — Install

```bash
cd crop-advisory-backend-v5
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
```

### Step 2 — Configure `.env`

```bash
cp .env.example .env
```

Fill in, at minimum:

| Variable | What it's for |
|---|---|
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_FROM_NUMBER` | Your Twilio credentials (or set `SMS_PROVIDER=textbee` instead — see README's "SMS providers" section) |
| `ADVISORY_TO_NUMBERS` | Comma-separated phone numbers to actually message (v5) |
| `EXPECTED_DEVICE_KEY` | Shared secret the ESP32 sends — required before exposing this to the internet |
| `SOWING_DATE` | Format `YYYY-MM-DD`; drives fertilizer/harvest timing |
| `GEMINI_API_KEY` | For LLM-paraphrased advisory text |
| `DATA_GOV_API_KEY` | Optional — enables mandi (market) price lookup |

Leave `ALERT_COOLDOWN_MINUTES` at its new default of `360` for real
deployment, or drop it to `5` while rehearsing a demo.

### Step 3 — Run the tests (no network, no SMS cost)

```bash
pytest tests/ -v
```

All 289 should pass. If any fail, check that `EXPECTED_DEVICE_KEY`,
`ADVISORY_TO_NUMBER` and `TWILIO_TO_NUMBER` are set in your shell/`.env` —
a couple of tests read config at import time.

### Step 4 — Run the server

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Visit `http://localhost:8000/dashboard`.

### Step 5 — Flash the ESP32

See `hardware/README.md` and `hardware/crop_advisory_node/config.h` for the
wiring, sensor calibration, and `DEVICE_KEY` (must match
`EXPECTED_DEVICE_KEY`).

### Step 6 — Deploy for real

Follow the README's "Host it on a domain (Render)" section. Before you flip
`PUBLIC_MODE=true`:
- `EXPECTED_DEVICE_KEY` must be a strong random value (16+ characters, not
  a placeholder) — the app refuses to start otherwise.
- Confirm `ADVISORY_TO_NUMBERS` has every number you actually want reached,
  in international format (`+91...`).
- Leave `ALERT_COOLDOWN_MINUTES=360` unless you have a specific reason to
  change it.

---

## Attribution

This project was originally built jointly. v5 is an independent extension
of that joint work — the multi-recipient delivery fix, the production alert
cadence, and the dashboard refresh above are new in this iteration; the
underlying architecture (state-change alerting, delivery queue with
retry/backoff, rule engine, dashboard) is the shared v1–v4 foundation
described in `README.md`.
