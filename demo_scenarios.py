"""
The "decision table" for demo purposes: one named, reproducible scenario per
alert condition the system can raise, so each can be shown to a judge on
demand instead of waiting for a real field condition to naturally occur.

Each scenario is a full sensor reading (what the ESP32 would have sent) plus,
for conditions that depend on crop age (fertilizer/harvest), an OVERRIDE of
days_since_sowing. This override is used ONLY by the demo scenario endpoint
(/demo/scenario/{name}) -- the real /sensor-data endpoint always computes
days_since_sowing from the actual configured SOWING_DATE, never from a
scenario. Demo mode and real operation cannot cross-contaminate each other.

RAIN_WARNING is intentionally NOT force-triggerable: it depends on the real
weather forecast, and faking it would defeat the entire point of the
rain-vs-irrigation cross-verification system this project is built around.
It's listed here for completeness, with an honest note instead of a button.
"""

SCENARIOS = {
    "sensor_fault_dht": {
        "title": "DHT22 sensor fault",
        "why_it_matters": (
            "Shows the system reporting a broken sensor honestly instead of "
            "inventing a plausible temperature/humidity reading."
        ),
        "expected_alert": "SENSOR_FAULT_DHT22",
        "sensor": {"soil_moisture": 50.0, "temperature": None, "humidity": None, "raining": False},
        "days_override": None,
    },
    "sensor_fault_soil": {
        "title": "Soil moisture sensor fault",
        "why_it_matters": "Same honesty principle, for the soil probe instead of the DHT22.",
        "expected_alert": "SENSOR_FAULT_SOIL",
        "sensor": {"soil_moisture": None, "temperature": 29.0, "humidity": 65.0, "raining": False},
        "days_override": None,
    },
    "low_moisture": {
        "title": "Low soil moisture",
        "why_it_matters": "The core irrigation alert -- tells the farmer to check and water the field.",
        "expected_alert": "LOW_MOISTURE",
        "sensor": {"soil_moisture": 15.0, "temperature": 30.0, "humidity": 55.0, "raining": False},
        "days_override": None,
    },
    "excess_moisture": {
        "title": "Excess soil moisture (rain vs. irrigation)",
        "why_it_matters": (
            "Triggers the rain-vs-irrigation cross-verification: the SMS will say whether "
            "the wetness is from confirmed recent rainfall or likely irrigation, based on "
            "real weather data -- not guessed."
        ),
        "expected_alert": "EXCESS_MOISTURE",
        "sensor": {"soil_moisture": 85.0, "temperature": 27.0, "humidity": 80.0, "raining": True},
        "days_override": None,
    },
    "fertilizer_basal": {
        "title": "Basal fertilizer due",
        "why_it_matters": "Simulates day 0 -- the basal fertilizer application window.",
        "expected_alert": "FERTILIZER_DUE_BASAL",
        "sensor": {"soil_moisture": 45.0, "temperature": 28.0, "humidity": 70.0, "raining": False},
        "days_override": 0,
    },
    "fertilizer_tillering": {
        "title": "Tillering fertilizer due",
        "why_it_matters": "Simulates day 20 -- the first nitrogen top-dressing window.",
        "expected_alert": "FERTILIZER_DUE_TILLERING",
        "sensor": {"soil_moisture": 45.0, "temperature": 28.0, "humidity": 70.0, "raining": False},
        "days_override": 20,
    },
    "fertilizer_panicle": {
        "title": "Panicle-initiation fertilizer due",
        "why_it_matters": "Simulates day 45 -- the second nitrogen top-dressing window.",
        "expected_alert": "FERTILIZER_DUE_PANICLE",
        "sensor": {"soil_moisture": 45.0, "temperature": 28.0, "humidity": 70.0, "raining": False},
        "days_override": 45,
    },
    "harvest_approaching": {
        "title": "Harvest window approaching",
        "why_it_matters": "Simulates day 110 -- 5 days before estimated maturity.",
        "expected_alert": "HARVEST_APPROACHING",
        "sensor": {"soil_moisture": 45.0, "temperature": 28.0, "humidity": 70.0, "raining": False},
        "days_override": 110,
    },
    "harvest_check_due": {
        "title": "Harvest check due",
        "why_it_matters": "Simulates day 116 -- past estimated maturity; prompts a check, not a command.",
        "expected_alert": "HARVEST_CHECK_DUE",
        "sensor": {"soil_moisture": 45.0, "temperature": 28.0, "humidity": 70.0, "raining": False},
        "days_override": 116,
    },
    "rain_warning": {
        "title": "Rain warning near harvest (not force-triggerable)",
        "why_it_matters": (
            "This alert only fires when BOTH the harvest window is near AND the real "
            "weather API currently forecasts rain. It is deliberately not force-triggerable "
            "here -- faking a weather condition would undermine the whole point of grounding "
            "this alert in real data. Try 'Harvest window approaching' on a day when rain is "
            "actually forecast for Bhatkal to see it fire naturally."
        ),
        "expected_alert": "RAIN_WARNING",
        "sensor": None,       # no button rendered for this one -- see dashboard.py
        "days_override": None,
    },
}


def get_button_scenarios() -> dict:
    """Only the scenarios that can actually be force-triggered (excludes rain_warning)."""
    return {name: s for name, s in SCENARIOS.items() if s["sensor"] is not None}
