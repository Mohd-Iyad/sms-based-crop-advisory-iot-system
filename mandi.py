"""
Fetches today's mandi (market) price for the configured commodity/district using
the data.gov.in Agmarknet dataset API.

Resource ID used: 9ef84268-d588-465a-a308-a864a43d0070
(Current daily price of various commodities from various markets - Mandi)

SECURITY NOTE: no API key is hardcoded here. If DATA_GOV_API_KEY is not set
in your .env, this returns {"available": False} instead of silently using a
shared public key baked into source code.
"""
from datetime import datetime

import requests
from config import DATA_GOV_API_KEY, MANDI_STATE, MANDI_DISTRICT, MANDI_COMMODITY
from http_errors import describe_error

MANDI_API_URL = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"


def _arrival_date_key(record: dict):
    """
    Sorts by arrival_date descending (freshest first) so a market with several
    days of records doesn't get an arbitrary/stale one just because it happened
    to come first in the API's response order. The API's arrival_date is
    DD/MM/YYYY; a record with a missing/unparseable date sorts last (oldest),
    never first, so it can't be mistaken for the freshest price.
    """
    raw = record.get("arrival_date")
    try:
        return datetime.strptime(raw, "%d/%m/%Y")
    except (TypeError, ValueError):
        return datetime.min


def get_mandi_price() -> dict:
    """
    Returns a structured dict with full record context so the SMS can say
    exactly which market/date the price is from, instead of an unlabelled
    number that might be from an unexpected market or a stale date:

      {"available": True, "market": ..., "arrival_date": ..., "commodity": ...,
       "variety": ..., "min_price": ..., "max_price": ..., "modal_price": ...}
      {"available": False}
    """
    if not DATA_GOV_API_KEY:
        print("[mandi.py] No DATA_GOV_API_KEY configured, skipping mandi lookup.")
        return {"available": False}

    try:
        params = {
            "api-key": DATA_GOV_API_KEY,
            "format": "json",
            "limit": 10,
            "filters[state]": MANDI_STATE,
            "filters[district]": MANDI_DISTRICT,
            "filters[commodity]": MANDI_COMMODITY,
        }
        response = requests.get(MANDI_API_URL, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        records = data.get("records", [])
        if not records:
            return {"available": False}

        # Deterministic, not "whatever the API happened to return first": the
        # freshest (most recent arrival_date) record wins.
        record = max(records, key=_arrival_date_key)
        modal_price = record.get("modal_price")
        if not modal_price:
            return {"available": False}

        return {
            "available": True,
            "market": record.get("market"),
            "arrival_date": record.get("arrival_date"),
            "commodity": record.get("commodity"),
            "variety": record.get("variety"),
            "min_price": record.get("min_price"),
            "max_price": record.get("max_price"),
            "modal_price": float(modal_price),
        }
    except Exception as e:
        print(f"[mandi.py] Mandi price API call failed: {describe_error(e)}")
        return {"available": False}
