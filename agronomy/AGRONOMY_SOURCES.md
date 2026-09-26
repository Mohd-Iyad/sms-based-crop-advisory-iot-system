# Agronomy Rule Sources — Paddy (Bhatkal Demo, v1.0)

This file exists so that when a judge asks "where did this number come
from?", there's a direct answer instead of a shrug. Every rule below is
**illustrative for a one-week prototype**, not a validated recommendation
for a specific variety or field.

| Rule ID | Rule | Value Used | Source | Verification Status |
|---|---|---|---|---|
| MOISTURE-LOW | Soil moisture index low-state threshold | enters <28, exits >35 | General irrigation-management practice (hysteresis band added to prevent state flicker) | Illustrative — not variety-specific |
| MOISTURE-HIGH | Soil moisture index excess-state threshold | enters >75, exits <65 | General waterlogging-avoidance practice | Illustrative — sensor reading is a relative index, not lab-measured volumetric water content |
| FERT-BASAL | Basal fertilizer timing | at sowing/transplanting | ICAR Kharif Agro-Advisory 2025 (general basal application guidance) | Adapted from general guidance, not variety-specific |
| FERT-TILLERING | First N top-dressing | days 18–25 after sowing | ICAR Kharif Agro-Advisory 2025 (split nitrogen application guidance) | Adapted from general guidance, not variety-specific |
| FERT-PANICLE | Second N top-dressing | days 40–50 after sowing | ICAR Kharif Agro-Advisory 2025 (split nitrogen application guidance) | Adapted from general guidance, not variety-specific |
| MATURITY-DAYS | Days to maturity | 115 days (default demo value) | General Kharif paddy range; ICAR documents specific coastal-Karnataka varieties (e.g. Sahyadri Panchamukhi) at 130–135 days | **Not verified for the actual variety grown in Bhatkal — must be corrected before real use** |
| HARVEST-CHECK | Harvest decision rule | "check due" at day ≥ maturity_days, not an automatic "ready" command | General guidance that grain color/moisture (commonly ~80–85% grains turned golden) is the real harvest signal | System flags a *check window*, not a harvest command — final call is the farmer's |
| RAIN-VS-IRRIGATION | Observed-rainfall threshold to attribute high moisture to rain vs. irrigation | ≥2.0mm summed over the trailing 6 hours (Open-Meteo observed/reanalysis data, not forecast) | Round-number engineering threshold, not an agronomic citation | Illustrative — a genuinely light drizzle below this threshold would be attributed to irrigation; tune `RECENT_RAIN_THRESHOLD_MM` in `weather.py` if this proves too strict/loose in the field |

## Prototype-status disclaimer (state this once, not repeatedly)

> The current implementation is a proof-of-concept. Agronomic thresholds are
> illustrative and would need to be validated against the actual paddy
> variety, local soil conditions, and Bhatkal KVK recommendations before
> any real deployment.

## How to correct this for a specific variety

1. Identify the exact paddy variety grown (ask a local farmer or the
   Bhatkal KVK).
2. Look up that variety's package-of-practices sheet from the Karnataka
   state agriculture department or the relevant KVK.
3. Update `CROP_PROFILE["maturity_days"]` and the `FERTILIZER_RULES` windows
   in `paddy_profile.py` to match.
4. Bump `RULE_VERSION` (e.g. to `paddy-bhatkal-v1.1`) so it's clear the
   numbers changed and when.
