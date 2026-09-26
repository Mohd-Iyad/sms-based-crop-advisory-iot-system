"""
Deterministic rule engine for PADDY (Bhatkal / coastal Karnataka, Kharif season).

This is the "brain" of the project, and it is intentionally the ONLY place
that decides anything agronomic. Everything downstream (LLM, SMS templates,
Twilio) just renders or delivers what this file decides -- nothing else is
allowed to interpret raw sensor data.

Key design choices (see the full audit this addresses for reasoning):
  - Hysteresis bands instead of single thresholds, so a reading sitting near
    a boundary doesn't flicker between states on sensor noise.
  - A missing/failed sensor reading (None) produces a SENSOR_FAULT alert
    code -- it is NEVER silently replaced with a plausible fake number.
  - "Harvest" produces a HARVEST_CHECK_DUE alert, not a command -- the
    actual harvest decision (grain color/moisture) is left to the farmer.
  - Every fact returned here is traceable to a specific rule with a source
    (see agronomy/paddy_profile.py and agronomy/AGRONOMY_SOURCES.md).
"""
from datetime import date, datetime

from agronomy.paddy_profile import (
    RULE_VERSION,
    CROP_PROFILE,
    MOISTURE_LOW_ENTER,
    MOISTURE_LOW_EXIT,
    MOISTURE_HIGH_ENTER,
    MOISTURE_HIGH_EXIT,
    FERTILIZER_RULES,
    HARVEST_APPROACHING_WINDOW_DAYS,
)


def compute_days_since_sowing(sowing_date_str: str, today: date = None) -> int:
    """
    Computed on the BACKEND using a configured sowing date -- the ESP32 does
    not need NTP time sync or any knowledge of the calendar at all. This
    removes an entire class of firmware failure (a bad NTP sync used to
    silently produce days_since_sowing = 0, which could wrongly trigger a
    basal-fertilizer alert on a 90-day-old crop).
    """
    if today is None:
        today = date.today()
    sowing_date = datetime.strptime(sowing_date_str, "%Y-%m-%d").date()
    days = (today - sowing_date).days
    return max(days, 0)


def _moisture_state(soil_moisture: float, previous_state: str) -> str:
    """
    Hysteresis-based state machine for soil moisture.
    previous_state is one of: "low", "normal", "high" (or None on first read).
    """
    if previous_state == "low" and soil_moisture < MOISTURE_LOW_EXIT:
        return "low"      # held by hysteresis until the reading rises past the EXIT point
    if previous_state == "high" and soil_moisture > MOISTURE_HIGH_EXIT:
        return "high"
    # Not held by hysteresis (normal, unknown, or just released): classify against the
    # ENTER thresholds. This also catches a jump straight from one extreme past the
    # other (e.g. "low" -> 90), which must read "high", not "normal".
    if soil_moisture < MOISTURE_LOW_ENTER:
        return "low"
    if soil_moisture > MOISTURE_HIGH_ENTER:
        return "high"
    return "normal"


def _fertilizer_alert(days_since_sowing: int):
    for rule in FERTILIZER_RULES:
        lo, hi = rule["window"]
        if lo <= days_since_sowing <= hi:
            return rule
    return None


def _harvest_state(days_since_sowing: int) -> dict:
    maturity_days = CROP_PROFILE["maturity_days"]
    days_remaining = maturity_days - days_since_sowing
    return {
        "days_remaining_estimate": max(days_remaining, 0),
        "harvest_check_due": days_remaining <= 0,
        "harvest_approaching": 0 < days_remaining <= HARVEST_APPROACHING_WINDOW_DAYS,
    }


def evaluate(
    soil_moisture,          # float or None
    temperature,            # float or None
    humidity,               # float or None
    raining,                # bool or None (from the rain sensor, "right now")
    days_since_sowing: int,
    previous_moisture_state: str = None,
    weather: dict = None,   # {"available": bool, "rain_expected": bool or None, "forecast": [...]}
    mandi: dict = None,     # {"available": bool, "modal_price": float, "market": str, ...}
    light_level=None,       # float or None -- ambient light index (LDR). Informational only, never gates an alert.
    recent_rainfall: dict = None,  # {"available": bool, "rained_recently": bool or None} -- observed, not forecast
) -> dict:
    """
    Main entry point. Returns:
      - facts: full structured state (for the dashboard / SMS template)
      - alert_codes: the list of conditions currently active (state_manager
        decides which of these actually warrant sending a new notification)
    """
    alert_codes = []
    sensor_faults = []

    # ---- DHT22 sensor fault handling: never fabricate ----
    if temperature is None or humidity is None:
        sensor_faults.append("SENSOR_FAULT_DHT22")
        alert_codes.append("SENSOR_FAULT_DHT22")

    # ---- Soil moisture (hysteresis state machine) ----
    moisture_state = None
    if soil_moisture is not None:
        moisture_state = _moisture_state(soil_moisture, previous_moisture_state)
        if moisture_state == "low":
            alert_codes.append("LOW_MOISTURE")
        elif moisture_state == "high":
            alert_codes.append("EXCESS_MOISTURE")
    else:
        sensor_faults.append("SENSOR_FAULT_SOIL")
        alert_codes.append("SENSOR_FAULT_SOIL")

    # ---- Fertilizer schedule ----
    fert_rule = _fertilizer_alert(days_since_sowing)
    if fert_rule:
        alert_codes.append(fert_rule["alert_code"])

    # ---- Harvest check (not a harvest command) ----
    harvest = _harvest_state(days_since_sowing)
    if harvest["harvest_check_due"]:
        alert_codes.append("HARVEST_CHECK_DUE")
    elif harvest["harvest_approaching"]:
        alert_codes.append("HARVEST_APPROACHING")

    # ---- Rain warning: only meaningful near harvest, and only if the
    #      weather API actually returned data (unknown != "no rain") ----
    rain_expected = None
    weather_available = bool(weather and weather.get("available"))
    if weather_available:
        rain_expected = weather.get("rain_expected")
        if rain_expected and (harvest["harvest_check_due"] or harvest["harvest_approaching"]):
            alert_codes.append("RAIN_WARNING")
    elif weather is not None:
        # The forecast was requested and failed. If it was never requested
        # (weather=None -- e.g. a reading with no new alert, so nothing needed it),
        # that is "not checked", which is NOT an outage and must not be reported as one.
        alert_codes.append("WEATHER_UNAVAILABLE")

    # ---- Rain vs. irrigation cross-verification ----
    # When the field is wet (EXCESS_MOISTURE), it matters WHY: a farmer who
    # just irrigated needs to know they may be overwatering; a field wet from
    # real rain needs no such warning. We only claim an answer when the
    # weather service actually confirms it either way -- an unavailable
    # check is reported as "unknown", never silently assumed to be irrigation
    # (that would be guessing, and could wrongly scold a farmer for rain).
    moisture_source = None
    if moisture_state == "high":
        if recent_rainfall and recent_rainfall.get("available"):
            moisture_source = "rain" if recent_rainfall.get("rained_recently") else "irrigation"
        else:
            moisture_source = "unknown"

    facts = {
        "rule_version": RULE_VERSION,
        "crop_profile": CROP_PROFILE,
        "days_since_sowing": days_since_sowing,

        "soil_moisture_index": soil_moisture,   # explicitly an INDEX, not volumetric %
        "moisture_state": moisture_state,       # "low" / "normal" / "high" / None (fault)

        "temperature_c": temperature,
        "humidity_percent": humidity,
        "sensor_faults": sensor_faults,

        "rain_detected_now": raining,           # from the physical rain sensor (None = not sent / unknown)
        "moisture_source": moisture_source,     # "rain" / "irrigation" / "unknown" / None -- only set when moisture_state == "high"
        "weather_checked": weather is not None,     # False = never fetched for this reading (not an outage)
        "weather_available": weather_available,
        "rain_expected_next_days": rain_expected,   # True / False / None (None = unknown, NOT "no rain")
        "weather_forecast": (weather or {}).get("forecast"),

        "light_level": light_level,             # LDR-derived ambient light index (0-100), informational only

        "fertilizer_due_rule": fert_rule,       # includes id, description, source -- or None

        "days_remaining_to_harvest_estimate": harvest["days_remaining_estimate"],
        "harvest_approaching": harvest["harvest_approaching"],
        "harvest_check_due": harvest["harvest_check_due"],

        "mandi": mandi or {"available": False},
    }

    return {
        "facts": facts,
        "alert_codes": sorted(set(alert_codes)),
        "moisture_state": moisture_state,  # returned separately so main.py can persist it for hysteresis
    }
