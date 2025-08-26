# google_calendar/calendar.py

from googleapiclient.discovery import build
from typing import Optional, List
from google.oauth2.credentials import Credentials
from shared.google_calendar.token_cache import get_cached_credentials
from fastapi import APIRouter
from shared import time
from shared.google_calendar.people import resolve_contacts
from store.people_store import save_contacts_to_runtime

calendar_router = APIRouter()

def utcnow_rfc3339() -> str:
    """Return current UTC time in RFC3339 format without microseconds, ending with Z."""
    return time.utcnow().replace(microsecond=0).isoformat().replace("+00:00", "Z")

@calendar_router.get("/google/events")
async def get_upcoming_events(user_id: str, max_results: int = 10):
    time_min = utcnow_rfc3339()
    try:
        events = pull_upcoming_events(user_id, time_min, max_results)
        return {"events": events}
    except Exception as e:
        return {"error": str(e)}

def pull_upcoming_events(
    user_id: str,
    time_min: Optional[str] = None,
    max_results: int = 10
) -> List[dict]:
    creds = get_cached_credentials(user_id)
    if not creds:
        raise Exception("Missing or invalid Google credentials")

    service = build("calendar", "v3", credentials=creds)

    if time_min is None:
        time_min = utcnow_rfc3339()

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime"
        )
        .execute()
    )
    return events_result.get("items", [])

def fetch_contacts(user_id: str, credentials: Optional[Credentials] = None) -> list[dict]:
    if not credentials:
        creds = get_cached_credentials(user_id)
        if not creds:
            raise Exception("Missing or invalid Google credentials")
    else:
        creds = credentials

    service = build("people", "v1", credentials=creds)

    all_connections = []
    page_token = None

    while True:
        request = (
            service.people()
            .connections()
            .list(
                resourceName="people/me",
                personFields="names,emailAddresses",
                pageSize=1000,
                pageToken=page_token
            )
        )
        results = request.execute()
        all_connections.extend(results.get("connections", []))

        page_token = results.get("nextPageToken")
        if not page_token:
            break

    return all_connections

contacts_router = APIRouter()

@contacts_router.get("/google/contacts")
async def get_contacts(user_id: str):
    try:
        contacts = fetch_contacts(user_id)
        resolved, needs_email = resolve_contacts(contacts)
        save_contacts_to_runtime(user_id, resolved)
        return {"contacts": resolved}
    except Exception as e:
        return {"error": str(e)}
