# google_calendar/token_cache.py

from typing import Optional
from google.oauth2.credentials import Credentials
from shared.google_calendar.tokens import get_valid_credentials

# Runtime in-memory cache
TOKEN_CACHE: dict[str, Credentials] = {}

def get_cached_credentials(user_id: str) -> Optional[Credentials]:
    creds = TOKEN_CACHE.get(user_id)
    if creds:
        return creds

    # Cold start: load and refresh
    creds = get_valid_credentials(user_id)
    if creds:
        TOKEN_CACHE[user_id] = creds
    return creds

def clear_cached_credentials(user_id: str):
    if user_id in TOKEN_CACHE:
        del TOKEN_CACHE[user_id]
