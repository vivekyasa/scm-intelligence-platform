"""Shared Gemini client. Reads GEMINI_API_KEY from the environment."""

from google import genai
from google.genai import types


def get_client() -> genai.Client:
    """One attempt per call, so our own retry and fallback logic stays fast."""
    try:
        return genai.Client(
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=1)
            )
        )
    except Exception:
        return genai.Client()
