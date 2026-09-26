"""
Builds the two outgoing messages from a set of alert codes + facts:

  - VOICE message: short, LLM-rendered, alert-codes-only (see llm.py) --
    no raw numbers, kept under ~40 seconds spoken.
  - SMS message: longer, fully deterministic (no LLM at all), includes the
    actual numbers (moisture index, temperature, mandi price) since SMS is
    read at the farmer's own pace and numbers matter there.

This split means: language generation is the LLM's job, numeric facts are
always handled by plain code. Neither one does the other's job.
"""
from llm import generate_voice_message, ALERT_CODE_DESCRIPTIONS
import sms_i18n


def build_voice_message(alert_codes: list) -> str:
    return generate_voice_message(alert_codes)


def _alert_description(lang: str, code: str) -> str:
    """Alert text in `lang`; English (llm.ALERT_CODE_DESCRIPTIONS) if untranslated; the code itself if unknown."""
    return sms_i18n.alert_text(lang, code) or ALERT_CODE_DESCRIPTIONS.get(code, code)


def build_sms_message(alert_codes: list, facts: dict, lang: str = "en", reading_time=None) -> str:
    """
    The SMS text, in `lang` (en / hi / kn). `reading_time` is when the backend
    received the reading (the ESP32 has no clock); it is printed so a late-arriving
    SMS is obviously dated. Numbers are always formatted here, as ASCII digits.
    """
    lang = sms_i18n.normalize_language(lang)
    t = lambda key, **values: sms_i18n.text(lang, key, **values)  # noqa: E731

    lines = [t("title")]
    if reading_time is not None:
        lines.append(t("reading", time=sms_i18n.format_reading_time(reading_time)))

    if facts.get("soil_moisture_index") is not None:
        lines.append(t("soil_moisture", value=f"{facts['soil_moisture_index']:.0f}"))
    if facts.get("temperature_c") is not None:
        lines.append(t("temperature", value=f"{facts['temperature_c']:.1f}"))
    if facts.get("humidity_percent") is not None:
        lines.append(t("humidity", value=f"{facts['humidity_percent']:.0f}"))
    if facts.get("light_level") is not None:
        lines.append(t("light", value=f"{facts['light_level']:.0f}"))

    lines.append("")
    lines.append(t("alerts_header"))
    for code in alert_codes:
        if code == "WEATHER_UNAVAILABLE":
            continue  # already covered by the dedicated weather section below
        lines.append(f"- {_alert_description(lang, code)}")

    weather_available = facts.get("weather_available")
    rain_expected = facts.get("rain_expected_next_days")
    if weather_available and rain_expected is not None:
        lines.append("")
        lines.append(t("rain_expected") if rain_expected else t("no_rain"))
    elif not weather_available:
        lines.append("")
        lines.append(t("weather_unavailable"))

    moisture_source = facts.get("moisture_source")
    if moisture_source == "rain":
        lines.append(t("cause_rain"))
    elif moisture_source == "irrigation":
        lines.append(t("cause_irrigation"))
    elif moisture_source == "unknown":
        lines.append(t("cause_unknown"))

    mandi = facts.get("mandi") or {}
    if mandi.get("available"):
        lines.append("")
        lines.append(t(
            "mandi",
            market=mandi.get("market", "unknown market"),
            date=mandi.get("arrival_date", "date unknown"),
            price=mandi.get("modal_price"),
        ))

    lines.append("")
    lines.append(t("rule_version", version=facts.get("rule_version", "unknown")))

    return "\n".join(lines)
