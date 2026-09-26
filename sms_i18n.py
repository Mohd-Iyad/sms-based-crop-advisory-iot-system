"""
Built-in SMS wording for English, Hindi and Kannada.

Every string the SMS can contain lives here, so a message is built entirely by
plain code: the wording comes from these tables and every number is formatted
by the caller with ordinary ASCII digits. Nothing is machine-translated at send
time, so a message can never silently fall back to English, never pays a network
round trip, and can never alter a value.

English alert descriptions are NOT duplicated here: llm.ALERT_CODE_DESCRIPTIONS
is the single English source (it also feeds the voice message), and
message_planner.py falls back to it for "en" and for any code missing below.

NOTE: the Hindi and Kannada wording is written to be short, since Indic SMS are
sent as UCS-2 (70 characters per part, 67 when a message spans several parts).
Have a native speaker review it before it goes to real farmers.
"""

# code -> name shown on the dashboard's language chips (each in its own script)
SUPPORTED_LANGUAGES = {"en": "English", "hi": "हिन्दी", "kn": "ಕನ್ನಡ"}
DEFAULT_LANGUAGE = "en"

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

STRINGS = {
    "en": {
        "title": "CROP ADVISORY - Paddy",
        "soil_moisture": "Soil moisture index: {value}/100",
        "temperature": "Temperature: {value}C",
        "humidity": "Humidity: {value}%",
        "light": "Ambient light index: {value}/100",
        "reading": "Reading: {time}",
        "alerts_header": "Alerts:",
        "rain_expected": "Rain expected in next 3 days.",
        "no_rain": "No significant rain expected in next 3 days.",
        "weather_unavailable": "(Weather forecast unavailable right now.)",
        "cause_rain": "Likely cause: recent rainfall (confirmed by weather data).",
        "cause_irrigation": (
            "Likely cause: irrigation, not rain (no significant rainfall recorded recently). "
            "Check for overwatering."
        ),
        "cause_unknown": "(Could not confirm whether this is rain or irrigation -- weather data unavailable.)",
        "mandi": "Mandi ({market}, {date}): Rs {price}/quintal",
        "rule_version": "Rule version: {version}",
    },
    "hi": {
        "title": "फसल सलाह - धान",
        "soil_moisture": "मिट्टी की नमी सूचकांक: {value}/100",
        "temperature": "तापमान: {value}°C",
        "humidity": "आर्द्रता: {value}%",
        "light": "प्रकाश सूचकांक: {value}/100",
        "reading": "रीडिंग: {time}",
        "alerts_header": "चेतावनियाँ:",
        "rain_expected": "अगले 3 दिनों में बारिश की संभावना है।",
        "no_rain": "अगले 3 दिनों में उल्लेखनीय बारिश की संभावना नहीं है।",
        "weather_unavailable": "(मौसम पूर्वानुमान अभी उपलब्ध नहीं है।)",
        "cause_rain": "संभावित कारण: हाल की बारिश (मौसम डेटा से पुष्टि)।",
        "cause_irrigation": (
            "संभावित कारण: सिंचाई, बारिश नहीं (हाल में कोई उल्लेखनीय बारिश दर्ज नहीं)। "
            "अधिक पानी की जाँच करें।"
        ),
        "cause_unknown": "(यह बारिश है या सिंचाई, पुष्टि नहीं हो सकी -- मौसम डेटा उपलब्ध नहीं।)",
        "mandi": "मंडी ({market}, {date}): रु {price}/क्विंटल",
        "rule_version": "नियम संस्करण: {version}",
    },
    "kn": {
        "title": "ಬೆಳೆ ಸಲಹೆ - ಭತ್ತ",
        "soil_moisture": "ಮಣ್ಣಿನ ತೇವಾಂಶ ಸೂಚ್ಯಂಕ: {value}/100",
        "temperature": "ತಾಪಮಾನ: {value}°C",
        "humidity": "ಆರ್ದ್ರತೆ: {value}%",
        "light": "ಬೆಳಕಿನ ಸೂಚ್ಯಂಕ: {value}/100",
        "reading": "ರೀಡಿಂಗ್: {time}",
        "alerts_header": "ಎಚ್ಚರಿಕೆಗಳು:",
        "rain_expected": "ಮುಂದಿನ 3 ದಿನಗಳಲ್ಲಿ ಮಳೆ ನಿರೀಕ್ಷಿಸಲಾಗಿದೆ.",
        "no_rain": "ಮುಂದಿನ 3 ದಿನಗಳಲ್ಲಿ ಗಮನಾರ್ಹ ಮಳೆ ನಿರೀಕ್ಷೆಯಿಲ್ಲ.",
        "weather_unavailable": "(ಹವಾಮಾನ ಮುನ್ಸೂಚನೆ ಈಗ ಲಭ್ಯವಿಲ್ಲ.)",
        "cause_rain": "ಸಂಭಾವ್ಯ ಕಾರಣ: ಇತ್ತೀಚಿನ ಮಳೆ (ಹವಾಮಾನ ಡೇಟಾದಿಂದ ದೃಢಪಟ್ಟಿದೆ).",
        "cause_irrigation": (
            "ಸಂಭಾವ್ಯ ಕಾರಣ: ನೀರಾವರಿ, ಮಳೆಯಲ್ಲ (ಇತ್ತೀಚೆಗೆ ಗಮನಾರ್ಹ ಮಳೆ ದಾಖಲಾಗಿಲ್ಲ). "
            "ಹೆಚ್ಚು ನೀರು ಹಾಯಿಸಿರುವುದನ್ನು ಪರಿಶೀಲಿಸಿ."
        ),
        "cause_unknown": "(ಇದು ಮಳೆಯೋ ನೀರಾವರಿಯೋ ಎಂದು ದೃಢಪಡಿಸಲಾಗಲಿಲ್ಲ -- ಹವಾಮಾನ ಡೇಟಾ ಲಭ್ಯವಿಲ್ಲ.)",
        "mandi": "ಮಂಡಿ ({market}, {date}): ರೂ {price}/ಕ್ವಿಂಟಲ್",
        "rule_version": "ನಿಯಮ ಆವೃತ್ತಿ: {version}",
    },
}

# Non-English alert descriptions. English lives in llm.ALERT_CODE_DESCRIPTIONS.
ALERTS = {
    "hi": {
        "LOW_MOISTURE": "मिट्टी में नमी कम है। खेत देखें और ज़रूरत हो तो सिंचाई करें।",
        "EXCESS_MOISTURE": "मिट्टी में नमी अधिक है। खेत में पानी जमा होने और जल निकासी की जाँच करें।",
        "FERTILIZER_DUE_BASAL": "बुवाई के समय बेसल खाद देने का समय है।",
        "FERTILIZER_DUE_TILLERING": "कल्ले फूटने की अवस्था में पहली नाइट्रोजन टॉप-ड्रेसिंग देने का समय है।",
        "FERTILIZER_DUE_PANICLE": "बाली बनने की अवस्था में दूसरी नाइट्रोजन टॉप-ड्रेसिंग देने का समय है।",
        "HARVEST_APPROACHING": "फसल आने वाले दिनों में अनुमानित कटाई के समय के करीब है।",
        "HARVEST_CHECK_DUE": "फसल अनुमानित कटाई के समय तक पहुँच गई है। कटाई से पहले दानों का रंग और नमी जाँचें।",
        "RAIN_WARNING": "अगले कुछ दिनों में बारिश का पूर्वानुमान है, जिससे कटाई या खेत का काम प्रभावित हो सकता है।",
        "SENSOR_FAULT_DHT22": "तापमान और आर्द्रता सेंसर जवाब नहीं दे रहा है, इसे जाँचें।",
        "SENSOR_FAULT_SOIL": "मिट्टी नमी सेंसर जवाब नहीं दे रहा है, इसे जाँचें।",
        "WEATHER_UNAVAILABLE": "मौसम पूर्वानुमान अस्थायी रूप से उपलब्ध नहीं है।",
    },
    "kn": {
        "LOW_MOISTURE": "ಮಣ್ಣಿನ ತೇವಾಂಶ ಕಡಿಮೆ ಇದೆ. ಹೊಲವನ್ನು ಪರಿಶೀಲಿಸಿ, ಅಗತ್ಯವಿದ್ದರೆ ನೀರು ಹಾಯಿಸಿ.",
        "EXCESS_MOISTURE": "ಮಣ್ಣಿನಲ್ಲಿ ತೇವಾಂಶ ಹೆಚ್ಚಾಗಿದೆ. ನೀರು ನಿಂತಿದೆಯೇ ಮತ್ತು ಒಳಚರಂಡಿ ಸರಿಯಿದೆಯೇ ಎಂದು ಪರಿಶೀಲಿಸಿ.",
        "FERTILIZER_DUE_BASAL": "ಬಿತ್ತನೆ ಸಮಯದಲ್ಲಿ ಬುನಾದಿ ಗೊಬ್ಬರ ಹಾಕುವ ಸಮಯ ಬಂದಿದೆ.",
        "FERTILIZER_DUE_TILLERING": "ಕಂದು ಒಡೆಯುವ ಹಂತದಲ್ಲಿ ಮೊದಲ ಸಾರಜನಕ ಮೇಲುಗೊಬ್ಬರ ಹಾಕುವ ಸಮಯ ಬಂದಿದೆ.",
        "FERTILIZER_DUE_PANICLE": "ತೆನೆ ಮೊಳಕೆಯೊಡೆಯುವ ಹಂತದಲ್ಲಿ ಎರಡನೇ ಸಾರಜನಕ ಮೇಲುಗೊಬ್ಬರ ಹಾಕುವ ಸಮಯ ಬಂದಿದೆ.",
        "HARVEST_APPROACHING": "ಬೆಳೆ ಇನ್ನು ಕೆಲವು ದಿನಗಳಲ್ಲಿ ನಿರೀಕ್ಷಿತ ಕಟಾವು ಸಮಯ ತಲುಪಲಿದೆ.",
        "HARVEST_CHECK_DUE": "ಬೆಳೆ ನಿರೀಕ್ಷಿತ ಕಟಾವು ಸಮಯ ತಲುಪಿದೆ. ಕಟಾವಿಗೆ ಮುನ್ನ ಕಾಳಿನ ಬಣ್ಣ ಮತ್ತು ತೇವಾಂಶ ಪರಿಶೀಲಿಸಿ.",
        "RAIN_WARNING": "ಮುಂದಿನ ಕೆಲವು ದಿನಗಳಲ್ಲಿ ಮಳೆ ಮುನ್ಸೂಚನೆ ಇದೆ, ಇದು ಕಟಾವು ಅಥವಾ ಹೊಲದ ಕೆಲಸಕ್ಕೆ ಅಡ್ಡಿಯಾಗಬಹುದು.",
        "SENSOR_FAULT_DHT22": "ತಾಪಮಾನ ಮತ್ತು ಆರ್ದ್ರತೆ ಸೆನ್ಸರ್ ಪ್ರತಿಕ್ರಿಯಿಸುತ್ತಿಲ್ಲ, ಪರಿಶೀಲಿಸಿ.",
        "SENSOR_FAULT_SOIL": "ಮಣ್ಣಿನ ತೇವಾಂಶ ಸೆನ್ಸರ್ ಪ್ರತಿಕ್ರಿಯಿಸುತ್ತಿಲ್ಲ, ಪರಿಶೀಲಿಸಿ.",
        "WEATHER_UNAVAILABLE": "ಹವಾಮಾನ ಮುನ್ಸೂಚನೆ ತಾತ್ಕಾಲಿಕವಾಗಿ ಲಭ್ಯವಿಲ್ಲ.",
    },
}


def normalize_language(code) -> str:
    """A supported language code, or English for anything blank/unknown."""
    code = (code or "").strip().lower()
    return code if code in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def is_supported(code) -> bool:
    return (code or "").strip().lower() in SUPPORTED_LANGUAGES


def text(lang: str, key: str, **values) -> str:
    """One template string in `lang`, filled in with `values`."""
    return STRINGS[normalize_language(lang)][key].format(**values)


def alert_text(lang: str, code: str):
    """The description of an alert code in `lang`, or None if there is no translation."""
    return ALERTS.get(normalize_language(lang), {}).get(code)


def format_reading_time(moment) -> str:
    """'21-Sep 14:32'. Month names are fixed English abbreviations (never locale dependent)."""
    return f"{moment.day:02d}-{_MONTHS[moment.month - 1]} {moment.hour:02d}:{moment.minute:02d}"
