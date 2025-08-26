from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from context.agents.event_item import EventItem
from shared.google_calendar.tokens import get_valid_credentials

def build_event_body(kwargs: dict) -> dict:
    """Builds a Google Calendar event body from EventItem kwargs."""
    body = {
        "summary": kwargs["title"],
        "description": kwargs.get("description"),
    }

    # Timed vs all-day
    if kwargs.get("all_day"):
        if not kwargs.get("date") or not kwargs.get("end_date"):
            raise ValueError("Missing date/end_date for all-day event")
        body["start"] = {"date": kwargs["date"]}
        body["end"] = {"date": kwargs["end_date"]}
    else:
        if not kwargs.get("datetime"):
            raise ValueError("Missing datetime for timed event")
        body["start"] = {
            "dateTime": kwargs["datetime"],
            "timeZone": kwargs.get("timezone", "UTC"),
        }
        body["end"] = {
            "dateTime": kwargs.get("end_datetime", kwargs["datetime"]),
            "timeZone": kwargs.get("timezone", "UTC"),
        }

    # Optional fields
    if kwargs.get("location"):
        body["location"] = kwargs["location"]

    if kwargs.get("participants"):
        body["attendees"] = [
            {"email": p.id, "responseStatus": p.status or "needsAction"}
            for p in kwargs["participants"]
        ]

    if kwargs.get("recurrence"):
        rec = kwargs["recurrence"]
        rule = f"RRULE:FREQ={rec.freq.upper()}"
        if rec.interval:
            rule += f";INTERVAL={rec.interval}"
        if rec.by_day:
            rule += f";BYDAY={','.join(rec.by_day)}"
        if rec.by_month_day:
            rule += f";BYMONTHDAY={','.join(map(str, rec.by_month_day))}"
        if rec.until:
            rule += f";UNTIL={rec.until}"
        if rec.count:
            rule += f";COUNT={rec.count}"
        body["recurrence"] = [rule]

    if kwargs.get("reminders"):
        body["reminders"] = {
            "useDefault": False,
            "overrides": [
                {"method": r.method, "minutes": r.minutes}
                for r in kwargs["reminders"]
            ],
        }

    return body

@tool(args_schema=EventItem)
def process_event(config: RunnableConfig, **kwargs) -> dict:
    """
    Create, update, or delete a Google Calendar event for the given user.
    Supports timed and all-day events.
    Returns: { ok: bool, item_id: str|None, error: str|None, code: str|None }
    """
    user_id = config["configurable"]["user_id"]

    if not user_id:
        return {"ok": False, "item_id": None, "error": "Missing user_id", "code": "no_user"}

    try:
        creds = get_valid_credentials(user_id)
        if not creds:
            return {"ok": False, "item_id": None, "error": "No valid credentials", "code": "no_creds"}

        service = build("calendar", "v3", credentials=creds)
        command = kwargs["command"]
        event_id = kwargs.get("item_id")

        if command in ["update", "delete"] and not event_id:
            return {"ok": False, "item_id": None, "error": "Missing event_id", "code": "no_id"}

        if command == "create":
            body = build_event_body(kwargs)
            event = service.events().insert(calendarId="primary", body=body).execute()
            return {"ok": True, "item_id": event["id"], "error": None, "code": None}

        elif command == "update":
            body = build_event_body(kwargs)
            event = service.events().patch(calendarId="primary", eventId=event_id, body=body).execute()
            return {"ok": True, "item_id": event["id"], "error": None, "code": None}

        elif command == "delete":
            service.events().delete(calendarId="primary", eventId=event_id).execute()
            return {"ok": True, "item_id": event_id, "error": None, "code": None}

        else:
            return {"ok": False, "item_id": None, "error": f"Unsupported command: {command}", "code": "bad_command"}

    except ValueError as ve:
        return {"ok": False, "item_id": None, "error": str(ve), "code": "bad_input"}
    except Exception as e:
        return {"ok": False, "item_id": None, "error": str(e), "code": "exception"}

if __name__ == "__main__":
    result = process_event.invoke(
        {
            "command": "create",
            "item_type": "event",
            "title": "Demo Meeting with Sarah",
            "description": "Testing event creation via Echo",
            "datetime": "2025-08-28T10:00:00+03:00",
            "end_datetime": "2025-08-28T11:00:00+03:00",
            "timezone": "Asia/Jerusalem",
        },
        {
            "configurable": {
                "user_id": "123"
            }
        }
    )
    print(result)
