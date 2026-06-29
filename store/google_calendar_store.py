from __future__ import annotations
from typing import List, Optional, Literal
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
from domain.contracts import ActionItemSummary
from shared.google_calendar.token_cache import get_cached_credentials
from shared import time


ASIA_JERUSALEM = ZoneInfo("Asia/Jerusalem")


def _ensure_rfc3339_z(dt: datetime) -> str:
    """UTC aware -> RFC3339 with Z, no microseconds."""
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    dt_utc = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt_utc.isoformat().replace("+00:00", "Z")


def _parse_local_jerusalem(dt_str: str) -> datetime:
    """Parse your user-facing datetime string, assume Asia/Jerusalem, return aware dt."""
    parsed = time.parse_datetime(dt_str)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ASIA_JERUSALEM)
    return parsed


def _event_start_dt(event: dict) -> Optional[datetime]:
    start = event.get("start", {})
    dt = start.get("dateTime")
    if not dt:
        # all-day events use "date"; skip them for action-item semantics
        return None
    # Let Google’s RFC3339 be parsed by Python
    return datetime.fromisoformat(dt.replace("Z", "+00:00"))


def _reminders_policy(item_type: str) -> dict:
    """
    For 'reminder' items: force push at start (popup, 0m).
    For everything else: keep the user's calendar defaults.
    """
    if item_type == "reminder":
        return {"useDefault": False, "overrides": [{"method": "popup", "minutes": 0}]}
    return {"useDefault": True}


class GoogleCalendarStore:
    """
    A Google Calendar–backed replacement for ActionItemStore.
    - Uses primary calendar.
    - Persists custom fields in extendedProperties.private
      (status, item_type, created_at, etc.)
    """

    def __init__(self):
        self.calendar_id = "primary"

    def _svc(self, user_id: str):
        creds = get_cached_credentials(user_id)
        if not creds:
            raise Exception("Missing or invalid Google credentials")
        return build("calendar", "v3", credentials=creds)

    # ---------- Status ----------
    def update_status(self, user_id: str, item_id: str, status: str) -> bool:
        """Update status in extendedProperties.private.status"""
        svc = self._svc(user_id)
        try:
            # read current to not clobber other private fields
            cur = svc.events().get(calendarId=self.calendar_id, eventId=item_id).execute()
            priv = (cur.get("extendedProperties", {}) or {}).get("private", {}) or {}
            priv["status"] = status
            patch = {"extendedProperties": {"private": priv}}
            svc.events().patch(calendarId=self.calendar_id, eventId=item_id, body=patch).execute()
            return True
        except Exception as e:
            print(f"[GCAL] update_status failed: {e}")
            return False

    # ---------- Create ----------
    def create_action_item(
        self,
        user_id: str,
        item_type: str,
        title: str,
        description: Optional[str],
        dt: Optional[str],
        location: Optional[str],
    ) -> str:
        """
        Create a Calendar event (default 60 min if no end given).
        Stores custom fields under extendedProperties.private.
        Returns the Google eventId.
        """
        svc = self._svc(user_id)

        start_dt_local: Optional[datetime] = None
        if dt:
            start_dt_local = _parse_local_jerusalem(dt)

        # Default start = now+5min, end = start+60min (keeps UX sane if dt missing)
        if not start_dt_local:
            start_dt_local = time.utcnow().astimezone(ASIA_JERUSALEM) + timedelta(minutes=5)

        end_dt_local = start_dt_local + timedelta(hours=1)

        event = {
            "summary": title,
            "description": description,
            "location": location,
            "start": {
                "dateTime": start_dt_local.isoformat(),
                "timeZone": "Asia/Jerusalem",
            },
            "end": {
                "dateTime": end_dt_local.isoformat(),
                "timeZone": "Asia/Jerusalem",
            },
            "extendedProperties": {
                "private": {
                    "status": "pending",
                    "item_type": item_type,
                    "created_at": time.utcnow().replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                }
            },
            # Reminders by policy: popup@0 for 'reminder', otherwise use defaults
            "reminders": _reminders_policy(item_type),
        }

        created = svc.events().insert(calendarId=self.calendar_id, body=event).execute()
        event_id = created["id"]
        print(f"[GCAL] Created event {event_id} for user {user_id}")
        return event_id

    # ---------- Update ----------
    def update_action_item(
        self,
        user_id: str,
        item_id: str,
        item_type: Optional[str],
        title: Optional[str],
        description: Optional[str],
        dt: Optional[str],
        location: Optional[str],
        status: Optional[str],
    ) -> bool:
        """
        Patch the event. Only provided fields are changed.
        """
        svc = self._svc(user_id)
        try:
            cur = svc.events().get(calendarId=self.calendar_id, eventId=item_id).execute()
            body = {}

            if title:
                body["summary"] = title
            if description is not None:
                body["description"] = description
            if location:
                body["location"] = location
            if dt:
                new_start_local = _parse_local_jerusalem(dt)
                new_end_local = new_start_local + timedelta(hours=1)  # keep 60m default
                body["start"] = {"dateTime": new_start_local.isoformat(), "timeZone": "Asia/Jerusalem"}
                body["end"] = {"dateTime": new_end_local.isoformat(), "timeZone": "Asia/Jerusalem"}

            # merge extendedProperties.private
            priv = (cur.get("extendedProperties", {}) or {}).get("private", {}) or {}
            # Determine final item_type after this patch
            final_item_type = item_type or priv.get("item_type", "event")
            if item_type:
                priv["item_type"] = item_type
            if status:
                priv["status"] = status
            priv["updated_at"] = time.utcnow().replace(microsecond=0).isoformat().replace("+00:00", "Z")
            body["extendedProperties"] = {"private": priv}

            # Reminders policy on update:
            # - if reminder → force popup@0
            # - else → revert to calendar defaults
            body["reminders"] = _reminders_policy(final_item_type)

            svc.events().patch(calendarId=self.calendar_id, eventId=item_id, body=body).execute()
            print(f"[GCAL] Updated event {item_id} for user {user_id}")
            return True
        except Exception as e:
            print(f"[GCAL] update_action_item failed: {e}")
            return False

    # ---------- Delete ----------
    def delete_action_item(self, user_id: str, item_id: str) -> bool:
        svc = self._svc(user_id)
        try:
            svc.events().delete(calendarId=self.calendar_id, eventId=item_id).execute()
            print(f"[GCAL] Deleted event {item_id} for user {user_id}")
            return True
        except Exception as e:
            print(f"[GCAL] delete_action_item failed: {e}")
            return False

    # ---------- Query by absolute time window for notifications ----------
    def query_action_items(self, start: datetime, end: Optional[datetime] = None) -> List[dict]:
        """
        NOTE: This is cross-user in your Firestore version, but Calendar calls are per user.
        Keep this method in app code where you *know* the user and call per user,
        or adjust signature to accept user_id.
        """
        if end is None:
            end = start + timedelta(minutes=1)

        raise NotImplementedError(
            "Google Calendar API is per-user. Call list() with a user_id-specific service."
        )

    # ---------- Upcoming per user ----------
    async def get_upcoming(self, user_id: str) -> List[ActionItemSummary]:
        svc = self._svc(user_id)
        now_utc = time.utcnow().replace(microsecond=0)
        future_utc = now_utc + timedelta(days=7)

        events = (
            svc.events()
            .list(
                calendarId=self.calendar_id,
                timeMin=_ensure_rfc3339_z(now_utc),
                timeMax=_ensure_rfc3339_z(future_utc),
                singleEvents=True,
                orderBy="startTime",
                maxResults=100,
            )
            .execute()
            .get("items", [])
        )

        items: List[ActionItemSummary] = []
        for ev in events:
            priv = (ev.get("extendedProperties", {}) or {}).get("private", {}) or {}
            status = priv.get("status", "pending")
            if status not in ("pending", "failed"):
                continue

            start_dt = _event_start_dt(ev)
            if not start_dt:
                continue  # skip all-day events for action semantics

            items.append(
                ActionItemSummary(
                    id=ev["id"],
                    action=ev.get("summary", "(ללא כותרת)"),
                    action_type=priv.get("item_type", "event"),
                    time=start_dt,
                    participants=[a["email"] for a in ev.get("attendees", [])] if ev.get("attendees") else [],
                    location=ev.get("location"),
                )
            )
        return items

    # ---------- Filtered fetch like your get_items ----------
    def get_items(
        self,
        user_id: str,
        status: Literal["all", "pending", "completed"] = "pending",
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> List[dict]:
        svc = self._svc(user_id)

        # Build list parameters
        params = {
            "calendarId": self.calendar_id,
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": 250,
        }

        if from_date:
            from_date = from_date.replace(tzinfo=ZoneInfo("Asia/Jerusalem")).astimezone(timezone.utc)
            params["timeMin"] = _ensure_rfc3339_z(from_date)
        if to_date:
            to_date = to_date.replace(tzinfo=ZoneInfo("Asia/Jerusalem")).astimezone(timezone.utc)
            params["timeMax"] = _ensure_rfc3339_z(to_date)

        events = svc.events().list(**params).execute().get("items", [])

        out: List[dict] = []
        for ev in events:
            priv = (ev.get("extendedProperties", {}) or {}).get("private", {}) or {}
            ev_status = priv.get("status", "pending")
            if status != "all" and ev_status != status:
                continue

            out.append(
                {
                    "item_id": ev["id"],
                    "user_id": user_id,
                    "item_type": priv.get("item_type", "event"),
                    "title": ev.get("summary"),
                    "description": ev.get("description"),
                    "datetime": _event_start_dt(ev),
                    "location": ev.get("location"),
                    "status": ev_status,
                    "extendedProperties": {"private": priv},
                }
            )
        return out
