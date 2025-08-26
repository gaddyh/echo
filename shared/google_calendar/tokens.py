# google_calendar/tokens.py

from google.oauth2.credentials import Credentials
from typing import Optional
from datetime import datetime
from db.base import db

TOKEN_COLLECTION = "google_tokens"
STATE_COLLECTION = "google_auth_state"

# tokens.py
from google.auth.transport.requests import Request as GoogleRequest
from google.auth.exceptions import RefreshError

def get_valid_credentials(user_id: str) -> Optional[Credentials]:
    creds = load_token_for_user(user_id)
    if creds is None:
        return None

    try:
        if creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
            save_token_for_user(user_id, creds)  # Persist the new token
        return creds
    except RefreshError:
        print(f"⚠️ Refresh failed for user: {user_id}")
        return None  # You can trigger re-auth here

def save_token_for_user(user_id: str, credentials: Credentials) -> None:
    db.collection(TOKEN_COLLECTION).document(user_id).set({
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes,
        "expiry": credentials.expiry.isoformat() if credentials.expiry else None,
    })

def load_token_for_user(user_id: str) -> Optional[Credentials]:
    doc = db.collection(TOKEN_COLLECTION).document(user_id).get()
    if not doc.exists:
        return None

    data = doc.to_dict()
    expiry = datetime.fromisoformat(data["expiry"]) if data.get("expiry") else None

    return Credentials(
        token=data["token"],
        refresh_token=data["refresh_token"],
        token_uri=data["token_uri"],
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        scopes=data["scopes"],
        expiry=expiry,
    )

def save_auth_state(state: str, user_id: str) -> None:
    db.collection(STATE_COLLECTION).document(state).set({"user_id": user_id})

def load_user_id_from_state(state: str) -> Optional[str]:
    doc = db.collection(STATE_COLLECTION).document(state).get()
    if not doc.exists:
        return None
    return doc.to_dict()["user_id"]

def delete_auth_state(state: str) -> None:
    db.collection(STATE_COLLECTION).document(state).delete()
