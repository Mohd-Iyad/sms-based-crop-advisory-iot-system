"""
Versioned agronomic rule data for PADDY. Kept separate from rule_engine.py's
logic so the *numbers* (which can be swapped for a different variety/KVK
recommendation) are cleanly separated from the *decision logic* (which stays
constant). See AGRONOMY_SOURCES.md in this same folder for what each number
is based on and its verification status.

These thresholds are illustrative, adapted from general ICAR Kharif guidance.
They are NOT validated against the specific paddy variety grown in Bhatkal
and must be replaced with exact local KVK numbers before any real deployment.
"""

RULE_VERSION = "paddy-bhatkal-demo-v1.0"

CROP_PROFILE = {
    "crop": "paddy",
    "variety": "unspecified (generic Kharif paddy assumption)",
    "cultivation_method": "transplanted",
    "maturity_days": 115,          # varies by variety; e.g. Sahyadri Panchamukhi (coastal Karnataka) runs 130-135 days
    "rule_version": RULE_VERSION,
    "location": "Bhatkal, Uttara Kannada, Karnataka",
}

# Soil moisture -- hysteresis bands instead of a single threshold, so the
# system doesn't flicker between states when the reading sits near a boundary.
MOISTURE_LOW_ENTER = 28.0    # enter LOW state when index drops below this
MOISTURE_LOW_EXIT = 35.0     # only leave LOW state once index rises above this
MOISTURE_HIGH_ENTER = 75.0   # enter EXCESS state when index rises above this
MOISTURE_HIGH_EXIT = 65.0    # only leave EXCESS state once index drops below this

# Fertilizer schedule: (day_range_start, day_range_end, alert_code, source_note)
FERTILIZER_RULES = [
    {
        "id": "FERT-BASAL",
        "window": (0, 0),
        "alert_code": "FERTILIZER_DUE_BASAL",
        "description": "Apply basal dose of fertilizer at sowing/transplanting.",
        "source": "ICAR Kharif Agro-Advisory 2025 (general basal application guidance)",
    },
    {
        "id": "FERT-TILLERING",
        "window": (18, 25),
        "alert_code": "FERTILIZER_DUE_TILLERING",
        "description": "Apply first nitrogen top-dressing during the tillering stage.",
        "source": "ICAR Kharif Agro-Advisory 2025 (split nitrogen application guidance)",
    },
    {
        "id": "FERT-PANICLE",
        "window": (40, 50),
        "alert_code": "FERTILIZER_DUE_PANICLE",
        "description": "Apply second nitrogen top-dressing at panicle initiation stage.",
        "source": "ICAR Kharif Agro-Advisory 2025 (split nitrogen application guidance)",
    },
]

# Harvest: a "check due" state, not an absolute "ready" command -- the
# actual decision (based on grain color/moisture) is left to the farmer.
HARVEST_APPROACHING_WINDOW_DAYS = 10   # days before estimated maturity to start warning
