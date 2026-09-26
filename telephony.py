"""
Delivers messages via SMS (Twilio or textbee, selected by SMS_PROVIDER) and,
if enabled, voice call (Twilio only). Every send is fully independent --
if one fails, it does not prevent or delay any other, and each has its own
explicit timeout so a slow/hanging request can't stall the whole pipeline.

Every result dict also carries `retryable: bool` on failure, so
services/delivery_queue.py can decide whether to schedule a backoff retry or
give up immediately: a timeout/connection error or an HTTP 429/5xx is
retryable (the provider or network may recover); any other 4xx (e.g. an
invalid/unverified number) is permanent -- retrying it would just waste
attempts on a request that can never succeed.
"""
import requests
from requests.auth import HTTPBasicAuth
from config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_FROM_NUMBER,
    TWILIO_VOICE,
    TWILIO_VOICE_LANGUAGE,
    SMS_PROVIDER,
    TEXTBEE_API_KEY,
    TEXTBEE_DEVICE_ID,
    ADVISORY_TO_NUMBER,
)

TWILIO_BASE_URL = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}"
TEXTBEE_SEND_URL = "https://api.textbee.dev/api/v1/gateway/send-sms"
REQUEST_TIMEOUT_SECONDS = 15


def _json_or_raw(response) -> dict:
    """Parse a JSON body, tolerating a non-JSON one (a 2xx must not be reported as a failure for that)."""
    try:
        body = response.json()
        return body if isinstance(body, dict) else {"raw": body}
    except Exception:
        return {"raw": getattr(response, "text", "")}


def _status_is_retryable(status_code) -> bool:
    """429 (rate limited) and 5xx (provider-side) are worth retrying; any other 4xx is permanent."""
    return status_code == 429 or (isinstance(status_code, int) and 500 <= status_code < 600)


def send_sms(message: str, to: str = None) -> dict:
    """Routes to the configured SMS provider. Never raises -- failures come back as a dict.

    `to` defaults to ADVISORY_TO_NUMBER for backward compatibility, but v5's
    multi-recipient fan-out (see services/delivery_queue.py) passes each
    job's own recipient explicitly, so a household with several registered
    numbers actually reaches all of them instead of only the first.
    """
    recipient = to or ADVISORY_TO_NUMBER
    if SMS_PROVIDER == "textbee":
        return _send_sms_textbee(message, recipient)
    return _send_sms_twilio(message, recipient)


def _send_sms_twilio(message: str, to: str = None) -> dict:
    try:
        url = f"{TWILIO_BASE_URL}/Messages.json"
        payload = {
            "From": TWILIO_FROM_NUMBER,
            "To": to or ADVISORY_TO_NUMBER,
            "Body": message,
        }
        response = requests.post(
            url,
            data=payload,
            auth=HTTPBasicAuth(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        body = _json_or_raw(response)
        success = response.status_code < 300
        result = {"success": success, "status_code": response.status_code, "body": body}
        if not success:
            # Twilio's error responses include a human-readable "message" and
            # a "code" (e.g. 21608 = unverified number, 572006 = trial
            # accounts can only send predefined templates) -- surface both
            # instead of just the bare HTTP status.
            result["error"] = f"Twilio {body.get('code', '?')}: {body.get('message', 'unknown error')}"
            result["retryable"] = _status_is_retryable(response.status_code)
        return result
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        print(f"[telephony.py] Twilio SMS send failed: {e}")
        return {"success": False, "error": str(e), "retryable": True}
    except Exception as e:
        print(f"[telephony.py] Twilio SMS send failed: {e}")
        return {"success": False, "error": str(e), "retryable": False}


def _send_sms_textbee(message: str, to: str = None) -> dict:
    """
    Sends SMS via textbee (https://textbee.dev) -- turns your own Android
    phone into the SMS sender, using its existing SIM/carrier plan. No
    trial-template restriction, no per-message cost, no DLT registration
    needed for this kind of low-volume personal use.

    Setup: install the textbee app on an Android phone, register it at
    textbee.dev to get an API key, put that in TEXTBEE_API_KEY.
    """
    try:
        headers = {"x-api-key": TEXTBEE_API_KEY}
        payload = {"recipients": [to or ADVISORY_TO_NUMBER], "message": message}
        if TEXTBEE_DEVICE_ID:
            payload["deviceId"] = TEXTBEE_DEVICE_ID
        response = requests.post(
            TEXTBEE_SEND_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
        )
        success = response.status_code < 300
        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text}
        result = {"success": success, "status_code": response.status_code, "body": body}
        if not success:
            result["error"] = f"textbee {response.status_code}: {body.get('message', body)}"
            result["retryable"] = _status_is_retryable(response.status_code)
        return result
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        print(f"[telephony.py] textbee SMS send failed: {e}")
        return {"success": False, "error": str(e), "retryable": True}
    except Exception as e:
        print(f"[telephony.py] textbee SMS send failed: {e}")
        return {"success": False, "error": str(e), "retryable": False}


def make_voice_call(message: str, to: str = None) -> dict:
    """
    Places an automated voice call reading `message` aloud via Twilio's
    <Say> TwiML verb. Voice is Twilio-only (textbee is SMS-only). Voice +
    language are configurable (see config.py). `to` defaults to
    ADVISORY_TO_NUMBER; see send_sms() above for why v5 usually passes it
    explicitly instead.
    """
    recipient = to or ADVISORY_TO_NUMBER
    try:
        safe_message = (
            message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        twiml = (
            f'<Response><Say voice="{TWILIO_VOICE}" language="{TWILIO_VOICE_LANGUAGE}">'
            f"{safe_message}</Say></Response>"
        )

        url = f"{TWILIO_BASE_URL}/Calls.json"
        payload = {
            "From": TWILIO_FROM_NUMBER,
            "To": recipient,
            "Twiml": twiml,
        }
        response = requests.post(
            url,
            data=payload,
            auth=HTTPBasicAuth(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        body = _json_or_raw(response)
        success = response.status_code < 300
        result = {"success": success, "status_code": response.status_code, "body": body}
        if not success:
            result["error"] = f"Twilio {body.get('code', '?')}: {body.get('message', 'unknown error')}"
            result["retryable"] = _status_is_retryable(response.status_code)
        return result
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        print(f"[telephony.py] Voice call failed: {e}")
        return {"success": False, "error": str(e), "retryable": True}
    except Exception as e:
        print(f"[telephony.py] Voice call failed: {e}")
        return {"success": False, "error": str(e), "retryable": False}
