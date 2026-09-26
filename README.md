# Voice-First Crop Advisory System (v5)

Full project repo: backend pipeline (this root folder) + ESP32 hardware/firmware
(in `hardware/`, with its own [hardware/README.md](hardware/README.md) and
wiring/flow/block diagrams).

> **Prototype status:** This is a proof-of-concept. Agronomic thresholds are
> illustrative and would need validation against the actual paddy variety,
> local soil conditions, and Bhatkal KVK recommendations before real
> deployment. See `agronomy/AGRONOMY_SOURCES.md` for exactly which numbers
> are sourced from where.

> **Delivery mode:** SMS-only by default. Voice calling is fully implemented
> and tested (`telephony.py` + `llm.py`) but disabled via a config flag
> (`ENABLE_VOICE_CALL=false`) to reduce the number of moving parts to
> rehearse for a live demo. This is a genuine implemented feature behind a
> switch, not an unbuilt roadmap item — set `ENABLE_VOICE_CALL=true` in
> `.env` to turn it back on with zero code changes. When disabled, the
> Gemini call for voice-message generation is skipped entirely too.

## SMS providers: Twilio trial vs. textbee

Twilio trial accounts restrict SMS to predefined templates (error
`572006`) and unverified recipients — real, documented limitations, not a
bug in this code. Two ways around it:

1. **Upgrade Twilio** (pay the small minimum, typically ~$20) — removes
   both restrictions instantly, no other changes needed.
2. **Switch to textbee** (free, no restrictions for this use case) — turns
   an old Android phone into the SMS sender, using its own SIM/carrier
   plan. Install the app, register at textbee.dev, get an API key, then in
   `.env` set `SMS_PROVIDER=textbee` and `TEXTBEE_API_KEY=...`. No other
   code changes — `telephony.py` routes to whichever provider is configured.

## What changed in v2 (responding to a full technical audit)

The original v1 backend worked, but had a real spam bug and several
honesty/security gaps. v2 fixes the highest-impact ones:

1. **State-change alerting, not every-reading alerting.** A field that stays
   dry for hours no longer triggers a phone call every 5 minutes — only a
   *new* condition, or one whose cooldown has expired, triggers delivery.
   See `state_manager.py`.
2. **Sensor faults are reported honestly, never faked.** If the DHT22 fails,
   the system says so (`SENSOR_FAULT_DHT22`) instead of sending a plausible
   fake temperature/humidity.
3. **Hysteresis, not a single threshold**, for soil moisture — prevents the
   system flickering between states when a reading sits near a boundary.
4. **The LLM only ever sees alert codes, never raw numbers** — it cannot
   hallucinate a wrong figure because it's never given one. All numeric
   facts (moisture index, temperature, mandi price) go into the SMS via a
   deterministic template, never through the LLM.
5. **"Harvest ready" became "harvest check due"** — a decision-support
   signal, not a command; the actual call is left to the farmer.
6. **Weather API failure means "unknown", never "no rain".** Silently
   turning an API failure into "safe/no" was a real correctness bug.
7. **Rule versioning + sourcing** — see `agronomy/`.
8. **Basic security**: a shared device-key header (`X-Device-Key`) so random
   requests can't trigger a real phone call, plus input-range validation and
   duplicate-sequence rejection. No API keys are hardcoded in source code
   anymore (previously a shared data.gov.in demo key was baked in).
9. **Separate voice (short) and SMS (detailed) messages**, instead of one
   long message read aloud on both channels.
10. **A tiny live dashboard** at `/dashboard` for demo day.

## What's new in v3: demo controls, rain-vs-irrigation, translation

11. **One-click demo scenarios (the "decision table")** — `demo_scenarios.py`
    defines a named, reproducible scenario for every alert the system can
    raise (low/excess moisture, each fertilizer window, harvest, both
    sensor faults). `GET /demo/scenarios` lists them; `POST
    /demo/scenario/{name}` fires one on demand, complete with a real SMS
    send — so every condition can be shown to a judge without waiting for
    it to occur naturally. `RAIN_WARNING` is deliberately **not**
    force-triggerable (see point 12) — faking weather would defeat the
    point of grounding that alert in real data.
12. **Rain-vs-irrigation cross-verification** — when `EXCESS_MOISTURE`
    fires, the backend checks Open-Meteo's *observed* (not forecast)
    rainfall for the last 6 hours before saying anything. The SMS then
    says whether the wetness is confirmed rain, likely irrigation, or
    (if the weather check itself failed) explicitly "unknown" — it never
    guesses either way. See `weather.get_recent_rainfall()` and the
    `moisture_source` fact in `rule_engine.py`.
13. **SMS language (English / Hindi / Kannada)** — the SMS wording comes
    from built-in templates in `sms_i18n.py`, with every number formatted by
    plain code, so nothing is translated at send time and a message can never
    fall back to English or alter a value. `TRANSLATE_SMS_TO` (`en`, `hi` or
    `kn`) sets the default; the dashboard's language chips (once unlocked with
    the device key) change it at runtime for both automatic and demo SMS, until
    the server restarts. Each SMS carries a `Reading:` time, and the dashboard
    banner shows whether the last SMS was sent or failed, with its full text.
14. **Dashboard demo panel + manual refresh** — a "Refresh" link next
    to the auto-refresh, and (once you enter the access key via "Enter access
    key", or add `?key=YOUR_DEVICE_KEY` to the URL) one
    button per force-triggerable scenario, plus the SMS language chips. Plain
    HTML `<form>` buttons, no JavaScript. The dashboard's CSP allows form
    posts to its own origin only (`form-action 'self'`).

## What's new in v5: multi-recipient delivery, real-world SMS cadence

v5 is a co-authored continuation of this project, focused on closing the gap
between "demo-day settings" and how the system should actually run once it's
watching a real field.

15. **Multi-recipient delivery** — `ADVISORY_TO_NUMBERS` (comma-separated,
    `.env`) lets more than one phone get the advisory: the farmer plus, say,
    a family member managing the field remotely. Each recipient gets its own
    `DeliveryJob` row with independent retry/backoff, so one bad or
    unreachable number never blocks or delays delivery to the others. This
    also closed a real gap in v4: the delivery job already stored a
    `recipient` field per job, but the actual Twilio/textbee call ignored it
    and always sent to one hardcoded number — `telephony.send_sms()` /
    `make_voice_call()` now take an explicit `to=`, and
    `services/delivery_queue.py` passes each job's own recipient through.
    `ADVISORY_TO_NUMBER` (singular) still works unchanged for a
    single-recipient setup.
16. **Production-realistic alert cadence.** `ALERT_COOLDOWN_MINUTES` now
    defaults to `360` (6 hours, roughly four updates a day) instead of the
    demo-day default of `5` minutes. A live field doesn't need a repeat
    "soil still dry" text every 5 minutes; four times a day is closer to how
    a farmer would actually want to be reached, and it keeps SMS cost and
    phone-buzzing sane. Drop it back to `5` in `.env` for a fast on-stage
    demo where you want to see a repeat quickly.
17. **Refreshed dashboard theme** — new accent color and title
    (`Crop Advisory v5`) to visually distinguish this iteration.

## What's in this folder

| File / folder | What it does |
|---|---|
| `main.py` | FastAPI app — ties everything together, handles auth + dedup |
| `models.py` | Input validation (range limits, required fields) |
| `rule_engine.py` | The "brain" — hysteresis, sensor-fault detection, versioned rules, rain-vs-irrigation |
| `state_manager.py` | State-change + cooldown logic (the anti-spam fix) |
| `demo_scenarios.py` | The decision table — one named, reproducible scenario per alert code |
| `message_planner.py` | Builds separate voice (short) vs SMS (detailed) messages |
| `llm.py` | Gemini calls — voice rendering (alert codes only). Its old SMS-translation helper is kept but no longer used |
| `sms_i18n.py` | English / Hindi / Kannada SMS wording (built-in templates; numbers are filled in by code) |
| `telephony.py` | Twilio/textbee SMS + Twilio voice call, independent error handling |
| `weather.py` | Open-Meteo forecast + observed-rainfall check — "unavailable" is distinct from "no rain" |
| `mandi.py` | data.gov.in mandi price lookup — full record detail, no hardcoded key |
| `dashboard.py` | Live-status HTML page with a demo control panel |
| `config.py` | Loads all settings from `.env` — zero hardcoded credentials |
| `agronomy/` | Versioned crop rules + `AGRONOMY_SOURCES.md` documenting where every number comes from |
| `tests/` | 250+ tests across rules, API, dashboard, integrations, and regressions (run with `pytest`) |

## Step 1 — Save the files and install dependencies

```bash
python -m venv venv
```
Activate it (`venv\Scripts\activate` on Windows, `source venv/bin/activate` on Mac/Linux), then:
```bash
pip install -r requirements.txt
```

## Step 2 — Fill in your `.env`

Copy `.env.example` → rename to `.env` → fill in your real Twilio/Gemini
keys, `EXPECTED_DEVICE_KEY` (must match your ESP32's `config.h`), and
`SOWING_DATE`.

## Step 3 — Run the tests (no network needed)

```bash
pytest tests/ -v
```
Every test should pass — they check every threshold (hysteresis
enter/exit points, fertilizer windows, harvest timing, sensor-fault
handling), the API, the dashboard and the SMS timing rules without needing
any real API keys or internet access (nothing here can send an SMS).

## Step 4 — Run the server locally

On Windows, double-click **`start_server.bat`** (or run it from a terminal). It
starts the server with `--host 0.0.0.0`, which is what lets the ESP32 reach it.
The equivalent command:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

(Plain `uvicorn main:app` only listens on this PC itself, so an ESP32 could
never reach it.) Run a single server process: the alert state is kept in memory.

### Prototype in a room (ESP32 + this PC on one Wi-Fi)

1. Put the ESP32 and this PC on the **same Wi-Fi network** (the ESP32 only does 2.4 GHz).
   School/office networks often isolate devices from each other or use a
   login page; if the ESP32 can't reach the PC, use a phone hotspot for both.
2. Find the PC's IPv4 address (`ipconfig` → "IPv4 Address") and put it in
   `hardware/crop_advisory_node/config.h`:
   `#define BACKEND_URL "http://192.168.x.x:8000/sensor-data"`.
   It can change when the router hands out a new address, so re-check it if
   readings stop arriving.
3. Allow the port through Windows Firewall, once, in an **Administrator** terminal:
   ```
   netsh advfirewall firewall add rule name="CropAdvisory8000" dir=in action=allow protocol=TCP localport=8000 profile=any
   ```
4. Check from a phone on the same Wi-Fi: `http://<PC-IP>:8000/dashboard` should load.
5. Flash the ESP32. In the Serial Monitor you should see a reading every 15 s,
   and the dashboard's "Last update" should stay under about 15 s.

**When SMS are sent:** immediately when a condition appears or an error occurs
(dry soil, too wet, a sensor fault…), then again every
`ALERT_COOLDOWN_MINUTES` (5) while it lasts. A healthy field sends nothing.
Fertilizer/harvest reminders repeat at most once a day
(`TIME_BASED_ALERT_COOLDOWN_MINUTES`). You can also send one on demand with the
dashboard's demo controls (marked `[TEST]`).

## Step 5 — Test the logic freely (costs ZERO SMS/calls)

Go to `http://127.0.0.1:8000/docs`, find **`POST /sensor-data-preview`**,
and try different scenarios — no device key needed, never delivers, never
touches your real device's cooldown state:

```json
{"device_id": "TEST", "sequence": 1, "soil_moisture": 15, "temperature": 30, "humidity": 65, "raining": false}
```

Try soil_moisture values across the hysteresis bands (below 28, 28–35,
above 75), omit `temperature`/`humidity` to see sensor-fault handling, etc.

## Step 6 — Confirm real delivery (uses Twilio SMS quota — do sparingly)

```
POST /sensor-data
```
with header `X-Device-Key: <your EXPECTED_DEVICE_KEY>` and a real body.
Because of the state-change logic, sending the **same** reading twice in a
row will **not** trigger a second SMS — this is intentional, not a bug.
To force a fresh demo alert, either change the values enough to cross a
threshold, or use:
```
POST /demo/trigger
```
(also requires the `X-Device-Key` header) — a fixed low-moisture scenario
for a repeatable live demo. By default this sends SMS only (see the
`ENABLE_VOICE_CALL` note above); it also places a voice call if you've
turned that on.

## Step 7 — View the dashboard

```
http://127.0.0.1:8000/dashboard
```
Shows the last reading, active alerts, the last SMS (sent or failed, with its
text) and last delivery status. Auto-refreshes every 15 seconds — good to have
open during a live demo. Use the "Refresh" link for an immediate manual refresh.
If the field node stops reporting, the page says "No recent data" after
`STALE_AFTER_MINUTES` (2) and dims the old numbers.

**Introducing a problem by hand (for a demo):** press **Enter access key** in the
"Introduce a problem" panel at the top and type your `EXPECTED_DEVICE_KEY` (the
secret from `.env` — the same value as `DEVICE_KEY` in `config.h`, *not* the
device name). You only do this once: the browser remembers it (a cookie, not the
address bar) until you press **Lock** or 12 hours pass.

- **A problem button** (DHT22 fault, low moisture, fertilizer due, …) makes up a
  reading with that problem, sends its SMS (marked `[TEST]`) and opens a
  **simulated** page showing it. The banner says *Problem introduced: … · SMS
  sent* (or *SMS FAILED* with the reason), and an amber bar reminds you the numbers
  are made up.
- **Back to real values** clears the simulation and returns to the real field
  readings. The real device and its alert state are never touched by any of this.
- **SMS language** chips (English / हिन्दी / ಕನ್ನಡ) change the language of every SMS.

The page pauses its auto-refresh while the key box is open so your typing isn't wiped.

**Default SMS language:** set `TRANSLATE_SMS_TO=en`, `hi` or `kn` in `.env` and
restart the server. The dashboard chips override it until the next restart.

**Security note:** putting the key in the URL is fine on your own laptop, but
never share a dashboard link that contains `?key=...` — rotate
`EXPECTED_DEVICE_KEY` if one ever leaks.

## Step 8 — Host it on a domain (Render) so it can be checked from anywhere

Push to GitHub (never commit `.env` or `config.h`), create a **Web Service** on
Render, and set:
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT` (one worker only)

Then add these under Render's **Environment** tab (do not upload your `.env`):

| Variable | Value |
|---|---|
| `PUBLIC_MODE` | `true` — refuses to start with a weak key, hides `/docs`, protects the preview endpoint |
| `EXPECTED_DEVICE_KEY` | a **new long random key**: `python -c "import secrets; print(secrets.token_urlsafe(24))"` |
| `TZ` | `Asia/Kolkata` (Render runs in UTC; this keeps SMS times and the rain check correct) |
| `PYTHON_VERSION` | `3.12.10` |
| `SMS_PROVIDER`, `TEXTBEE_API_KEY`, `TEXTBEE_DEVICE_ID`, `ADVISORY_TO_NUMBER` | as in your `.env` (textbee works over the internet; the phone just needs data and its SIM) |
| `SOWING_DATE`, `LOCATION_NAME`, `TRANSLATE_SMS_TO`, … | as in your `.env` |

For your own domain, add it under the service's **Custom Domains** and create
the DNS record Render shows; https is automatic.

**Point the ESP32 at it.** In `config.h` set
`#define BACKEND_URL "https://<your-domain>/sensor-data"` and
`#define DEVICE_KEY "<the same new key>"`, then re-flash. The sketch handles
`https://` itself. Use the `https://` address directly (an `http://` address
that gets redirected will fail). Note that it encrypts the traffic but does not
verify the server certificate; for that, pin a root certificate with
`setCACert()`.

**What is public.** Anyone with the address can *view* the dashboard (readings,
alerts, last SMS text). Sending SMS, changing the language and the preview
endpoint all need the key. Don't share links containing `?key=`. Rotate the key
(server + `config.h`) if it leaks, and also rotate the textbee key if this
folder was ever zipped or shared.

**Known limitations (stated honestly):**
- The state/cooldown store is in-memory. A restart or redeploy resets it, so
  active alerts are texted again straight away. Render's free tier also
  sleeps after inactivity: the ESP32's 15 s readings keep it awake, but a
  cold start takes 30–60 s, so prefer an always-on plan for real use. A real
  deployment would use a small persistent store (SQLite/Redis); the
  architecture isolates this in `state_manager.py` so that swap is one file.
- There is no rate limiting, and no alert if the ESP32 goes silent (the
  dashboard shows "No recent data", but nothing is texted).

## Troubleshooting

- **401 Unauthorized on `/sensor-data`**: check that `X-Device-Key` matches
  `EXPECTED_DEVICE_KEY` exactly.
- **No SMS on a repeated reading:** expected — see Step 6.
- **Gemini call fails silently:** falls back to a deterministic template
  automatically — check logs for the reason, but delivery still proceeds.
- **Mandi price shows unavailable:** either `DATA_GOV_API_KEY` isn't set, or
  that mandi/commodity/date combination has no record today (expected on
  Sundays/holidays).

## For your demo pitch

Don't say "Gemini analyzes the field and tells the farmer what to do." Say:
"The agricultural decision is produced by deterministic, versioned rules
(`rule_version` is returned with every response). SMS delivery uses a fully
deterministic template — no LLM involved at all, so nothing about the
numbers a farmer sees can be hallucinated. Voice calling is also fully
built, using Gemini purely as a language-rendering layer that never sees a
raw number — it's switched off for today's demo to keep the moving parts
manageable, not because it doesn't work."

A strong live demo sequence:
1. **Action** — dip the soil sensor in water/dry it out → watch the
   dashboard change → SMS arrives.
2. **No-action** — same dry reading again within the next few minutes →
   dashboard updates, but no second SMS until the 5-minute cooldown ends (the
   anti-spam fix, visibly proven).
3. **Failure handling** — unplug the DHT22 → dashboard shows a sensor-fault
   alert instead of a fake reading.

If a judge asks "why no voice call today?": "Voice is implemented and
tested — see `ENABLE_VOICE_CALL` in the config — we scoped it off for this
demo specifically to keep the number of live external dependencies low and
reliable on stage, not because it's unbuilt."
