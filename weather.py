"""
Fetches a short-range rain forecast using Open-Meteo (free, no API key required).
Docs: https://open-meteo.com/en/docs

IMPORTANT: on failure this returns {"available": False, "rain_expected": None},
NEVER {"rain_expected": False}. A failed API call means "we don't know", not
"no rain" -- silently treating unknown as "safe/no" is a real correctness bug,
not just a style choice, since it could suppress a genuine rain warning.
"""
import requests
from datetime import datetime
from config import LOCATION_LAT, LOCATION_LON
from http_errors import describe_error

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
RAIN_THRESHOLD_MM = 5.0


def get_weather() -> dict:
    """
    Returns a structured dict:
      {"available": True,  "rain_expected": bool, "forecast": [{"date": ..., "rain_mm": ...}, ...]}
      {"available": False, "rain_expected": None, "forecast": None}
    """
    try:
        params = {
            "latitude": LOCATION_LAT,
            "longitude": LOCATION_LON,
            "daily": "precipitation_sum",
            "forecast_days": 3,
            "timezone": "Asia/Kolkata",
        }
        response = requests.get(OPEN_METEO_URL, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        dates = data.get("daily", {}).get("time", [])
        rain_values = data.get("daily", {}).get("precipitation_sum", [])
        forecast = [
            {"date": d, "rain_mm": mm} for d, mm in zip(dates, rain_values)
        ]
        # Open-Meteo can return null for a day it has no figure for. Skip those days
        # rather than letting one null throw away an otherwise valid forecast; but if
        # NO day has a figure there is nothing to base an answer on -> "unknown".
        known = [mm for mm in rain_values if mm is not None]
        if not known:
            raise ValueError("no precipitation figures in response")
        rain_expected = any(mm >= RAIN_THRESHOLD_MM for mm in known)

        return {"available": True, "rain_expected": rain_expected, "forecast": forecast}
    except Exception as e:
        print(f"[weather.py] Weather API call failed, marking as unavailable: {describe_error(e)}")
        return {"available": False, "rain_expected": None, "forecast": None}


RECENT_RAIN_WINDOW_HOURS = 6
RECENT_RAIN_THRESHOLD_MM = 2.0


def get_recent_rainfall() -> dict:
    """
    Checks whether it has ACTUALLY rained recently (observed, not forecast) --
    used to distinguish "the field is wet because it rained" from "the field
    is wet because the farmer irrigated it". Open-Meteo's `past_days=1`
    parameter returns recent hourly precipitation alongside the forecast.

    Returns:
      {"available": True, "rained_recently": bool, "mm_last_6h": float}
      {"available": False, "rained_recently": None, "mm_last_6h": None}

    Like get_weather(), an API failure is reported as UNKNOWN, never as
    "no rain" -- we don't want to wrongly blame irrigation for a wet field
    just because the weather API happened to be down.
    """
    try:
        params = {
            "latitude": LOCATION_LAT,
            "longitude": LOCATION_LON,
            "hourly": "precipitation",
            "past_days": 1,
            "forecast_days": 1,
            "timezone": "Asia/Kolkata",
        }
        response = requests.get(OPEN_METEO_URL, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        times = data.get("hourly", {}).get("time", [])
        values = data.get("hourly", {}).get("precipitation", [])
        if not times or not values:
            raise ValueError("no hourly precipitation data in response")

        # Find the most recent hour that has already happened, then sum the
        # window of hours immediately before (and including) it.
        now_iso_hour = datetime.now().strftime("%Y-%m-%dT%H:00")
        past_indices = [i for i, t in enumerate(times) if t <= now_iso_hour]
        if not past_indices:
            raise ValueError("no past hours found in response")
        last_index = past_indices[-1]
        window = values[max(0, last_index - RECENT_RAIN_WINDOW_HOURS + 1): last_index + 1]
        known = [mm for mm in window if mm is not None]
        if not known:
            raise ValueError("no precipitation figures in the recent window")

        total_mm = sum(known)
        return {
            "available": True,
            "rained_recently": total_mm >= RECENT_RAIN_THRESHOLD_MM,
            "mm_last_6h": round(total_mm, 1),
        }
    except Exception as e:
        print(f"[weather.py] Recent-rainfall check failed, marking as unavailable: {describe_error(e)}")
        return {"available": False, "rained_recently": None, "mm_last_6h": None}
