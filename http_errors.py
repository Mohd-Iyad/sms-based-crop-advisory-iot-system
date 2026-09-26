"""
Safe one-line descriptions of exceptions, for logs and API responses.

`str(requests.HTTPError)` (and several other requests exceptions) contains the
full request URL. For Gemini / data.gov.in the API key travels in the URL query
string, so logging the raw exception prints the secret into the server logs.
This describes the failure without ever including the URL.
"""
import requests


def describe_error(exc: Exception) -> str:
    if isinstance(exc, requests.RequestException):
        response = getattr(exc, "response", None)
        if response is not None:
            return f"{type(exc).__name__} (HTTP {response.status_code})"
        return type(exc).__name__
    return f"{type(exc).__name__}: {exc}"
