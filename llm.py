"""
Turns a list of ALERT CODES (not raw sensor numbers) into a short, natural
spoken voice message. This is a deliberately stronger constraint than
"paraphrase this JSON" -- the LLM never receives any number at all (no
temperature, no moisture %, no price), so it structurally CANNOT hallucinate
a wrong number, because it never has one to begin with. Numeric facts go
into the SMS via a separate deterministic template (see message_planner.py),
never through the LLM.
"""
import json
import re
import requests
from config import GEMINI_API_KEY
from http_errors import describe_error

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)

ALERT_CODE_DESCRIPTIONS = {
    "LOW_MOISTURE": "The soil moisture is low. The farmer should check the field and irrigate if needed.",
    "EXCESS_MOISTURE": "The soil is showing high moisture. The farmer should check for standing water and drainage.",
    "FERTILIZER_DUE_BASAL": "It is time to apply the basal fertilizer dose at sowing.",
    "FERTILIZER_DUE_TILLERING": "It is time to apply the first nitrogen top-dressing, at the tillering stage.",
    "FERTILIZER_DUE_PANICLE": "It is time to apply the second nitrogen top-dressing, at panicle initiation stage.",
    "HARVEST_APPROACHING": "The crop is approaching its estimated harvest window in the coming days.",
    "HARVEST_CHECK_DUE": "The crop has reached its estimated harvest window. The farmer should check grain color and moisture before deciding to harvest.",
    "RAIN_WARNING": "Rain is forecast in the next few days, which may affect harvesting or field work.",
    "SENSOR_FAULT_DHT22": "The temperature and humidity sensor is not responding and should be checked.",
    "SENSOR_FAULT_SOIL": "The soil moisture sensor is not responding and should be checked.",
    "WEATHER_UNAVAILABLE": "Weather forecast data is temporarily unavailable.",
}

SYSTEM_INSTRUCTION_TEXT = """You are a language renderer, not an advisor.
You will be given a list of short plain-English alert descriptions that have
already been decided by an expert rule-based system. Your ONLY job is to
combine them into ONE short, warm, natural-sounding spoken message for a
farmer receiving a phone call.

Strict rules:
- Do NOT add any fact, number, date, or recommendation that is not present
  in the descriptions given to you.
- Do NOT invent numbers, percentages, prices, or measurements of any kind.
- Do NOT omit any of the given alert descriptions.
- Keep the message under 40 seconds when spoken aloud (roughly 90-110 words maximum).
- Speak directly to the farmer, e.g. "Your paddy field..." not "The farmer's field...".
- Begin with a brief greeting and end with a brief closing.
"""


def generate_voice_message(alert_codes: list, language_note: str = "English") -> str:
    """
    Renders the given alert codes into a spoken message. Falls back to a
    simple deterministic template (no LLM) if the API call fails, so a rate
    limit or network issue on demo day never breaks delivery.
    """
    descriptions = [ALERT_CODE_DESCRIPTIONS.get(code, code) for code in alert_codes]

    if not descriptions:
        return ""

    try:
        payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION_TEXT}]},
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                f"Render this in {language_note}. Alert descriptions (JSON):\n"
                                f"{json.dumps(descriptions, ensure_ascii=False)}"
                            )
                        }
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 250},
        }
        # The key goes in a header, not the URL, so it can never end up in a logged URL.
        response = requests.post(
            GEMINI_URL,
            json=payload,
            headers={"x-goog-api-key": GEMINI_API_KEY},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        message = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        if not message:
            raise ValueError("empty model response")
        # The model is never GIVEN a number, but nothing stops it from inventing one.
        # The spoken message must not contain any figure the rules didn't produce, so
        # a reply with digits is rejected in favour of the deterministic template.
        if any(ch.isdigit() for ch in message):
            raise ValueError("model reply contained digits")
        return message
    except Exception as e:
        print(f"[llm.py] Gemini call failed, using fallback template: {describe_error(e)}")
        return _fallback_voice_message(descriptions)


def _fallback_voice_message(descriptions: list) -> str:
    """A deterministic, no-LLM backup message -- just joins the descriptions."""
    if not descriptions:
        return ""
    intro = "Hello, this is your farm advisory. "
    body = " ".join(descriptions)
    outro = " Thank you."
    return intro + body + outro


LANGUAGE_NAMES = {
    "kn": "Kannada", "hi": "Hindi", "te": "Telugu", "ta": "Tamil",
    "mr": "Marathi", "en": "English",
}

TRANSLATE_SYSTEM_INSTRUCTION = (
    "You are a precise translator. Translate the given SMS text exactly as "
    "written. Do not add, remove, explain, or summarise anything. Keep every "
    "number, date, and price exactly as it appears in the original."
)


def translate_sms_message(text: str, target_lang_code: str) -> str:
    """
    Translates an ALREADY-FINALIZED, fully deterministic SMS into another
    language -- this is translation only, never generation, so it cannot add
    a new fact. As an extra safety check: every run of digits in the English
    original (moisture index, temperature, prices, rule version) must appear
    unchanged in the translation, or the translation is discarded and the
    English original is sent instead. A mistranslated word is a readability
    problem; a silently altered number is a trust problem, so numbers are
    never left to the model's judgement.
    """
    if not target_lang_code or target_lang_code == "en":
        return text

    language_name = LANGUAGE_NAMES.get(target_lang_code, target_lang_code)
    try:
        payload = {
            "systemInstruction": {"parts": [{"text": TRANSLATE_SYSTEM_INSTRUCTION}]},
            "contents": [{"parts": [{"text": f"Translate this SMS into {language_name}:\n\n{text}"}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 400},
        }
        response = requests.post(
            GEMINI_URL,
            json=payload,
            headers={"x-goog-api-key": GEMINI_API_KEY},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        translated = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        if not translated:
            raise ValueError("empty translation")

        original_numbers = re.findall(r"\d+(?:\.\d+)?", text)
        missing = [n for n in original_numbers if n not in translated]
        if missing:
            raise ValueError(f"translation dropped or altered number(s): {missing}")

        return translated
    except Exception as e:
        print(f"[llm.py] SMS translation to {target_lang_code} failed, sending English original: {describe_error(e)}")
        return text
