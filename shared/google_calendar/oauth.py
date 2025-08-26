# google_calendar/oauth.py

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
import os
from shared.google_calendar.calendar import fetch_contacts
from shared.google_calendar.people import resolve_contacts
from store.people_store import save_contacts_to_runtime

from shared.google_calendar.tokens import (
    save_token_for_user,
    save_auth_state,
    load_user_id_from_state,
    delete_auth_state,
)

google_router = APIRouter()

# Path to your secrets directory or default
secrets_dir = os.getenv("SECRETS_DIR", ".secrets")
CLIENT_SECRET_FILE = os.path.join(secrets_dir, "client_secret.json")

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/contacts.readonly"
]

REDIRECT_URI = "https://inme-1.onrender.com/google/oauth2callback"  # Set this to your deployed domain
REDIRECT_URI = "http://localhost:8000/google/oauth2callback"  # Set this to your deployed domain

@google_router.get("/google/auth-url")
async def google_auth_url(user_id: str):
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true"
    )

    save_auth_state(state, user_id)

    return {"auth_url": auth_url}

@google_router.get("/google/oauth2callback")
async def oauth2callback(request: Request):
    state = request.query_params.get("state")
    code = request.query_params.get("code")

    if not state or not code:
        raise HTTPException(status_code=400, detail="Missing state or code")

    user_id = load_user_id_from_state(state)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=SCOPES,
        state=state,
        redirect_uri=REDIRECT_URI
    )
    flow.fetch_token(code=code)
    credentials = flow.credentials

    save_token_for_user(user_id, credentials)
    delete_auth_state(state)

    contacts = fetch_contacts(user_id, credentials)
    resolved, needs_email = resolve_contacts(contacts)
    #save_contacts_to_runtime(user_id, resolved)
    return RedirectResponse(url="/success")  # Customize for your frontend
