from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from googleapiclient.errors import HttpError

from store.google_calendar_store import GoogleCalendarStore
from store.action_item_store import ActionItemStore
from shared.google_calendar.token_cache import get_cached_credentials
from context.agents.action_item import ActionItem

@tool(args_schema=ActionItem)
def process_self_action(config: RunnableConfig, **kwargs) -> dict:
    """
    process an action item (reminder, task, or event).
    Returns a dict payload with success status and where it was written.
    """
    action = ActionItem(**kwargs)
    user_id = config["configurable"]["user_id"]

    google = GoogleCalendarStore()
    fs = ActionItemStore()

    def ok(payload):  # consistent response
        return {"ok": True, **payload}
    def fail(msg, code=None):
        return {"ok": False, "error": msg, "code": code, "item_id": None}

    is_authed = bool(get_cached_credentials(user_id))

    try:
        # ---------- CREATE ----------
        if action.command == "create":
            if is_authed:
                try:
                    g_id = google.create_action_item(
                        user_id, action.item_type, action.title,
                        action.description, action.datetime, action.location
                    )
                    # Mirror reminders to Firestore as well
                    if action.item_type == "reminder":
                        fs.create_action_item(
                            user_id, action.item_type, action.title,
                            action.description, action.datetime, action.location
                        )
                    return ok({"item_id": g_id, "store": "google", "sync_status": "in_sync"})
                except HttpError as e:
                    if e.resp.status not in (401, 403):
                        return fail(f"google_error:{e.resp.status}", code=e.resp.status)
                    # treat 401/403 as no-auth fallback

            # No auth (or 401/403): write EVERYTHING to Firestore
            f_id = fs.create_action_item(
                user_id, action.item_type, action.title,
                action.description, action.datetime, action.location
            )
            return ok({"item_id": f_id, "store": "firestore", "sync_status": "pending_google"})

        # ---------- UPDATE ----------
        elif action.command == "update":
            if is_authed:
                try:
                    google.update_action_item(
                        user_id, action.item_id, action.item_type, action.title,
                        action.description, action.datetime, action.location, action.status
                    )
                    if action.item_type == "reminder":
                        fs.update_action_item(
                            user_id, action.item_id, action.item_type, action.title,
                            action.description, action.datetime, action.location, action.status
                        )
                    return ok({"item_id": action.item_id, "store": "google", "sync_status": "in_sync"})
                except HttpError as e:
                    if e.resp.status not in (401, 403):
                        return fail(f"google_error:{e.resp.status}", code=e.resp.status)
                    # fall through to FS as no-auth

            # No auth (or 401/403): update EVERYTHING in Firestore
            fs.update_action_item(
                user_id, action.item_id, action.item_type, action.title,
                action.description, action.datetime, action.location, action.status
            )
            return ok({"item_id": action.item_id, "store": "firestore", "sync_status": "pending_google"})

        # ---------- DELETE ----------
        elif action.command == "delete":
            if is_authed:
                try:
                    google.delete_action_item(user_id, action.item_id)
                    if action.item_type == "reminder":
                        fs.delete_action_item(user_id, action.item_id)
                    return ok({"item_id": action.item_id, "store": "google", "sync_status": "in_sync"})
                except HttpError as e:
                    if e.resp.status not in (401, 403):
                        return fail(f"google_error:{e.resp.status}", code=e.resp.status)
                    # fall through to FS as no-auth

            # No auth (or 401/403): delete in Firestore for ALL types
            fs.delete_action_item(user_id, action.item_id)
            return ok({"item_id": action.item_id, "store": "firestore", "sync_status": "pending_google"})

        return fail("unknown_command")

    except Exception as e:
        print("process_self_action error:", e)
        return fail("unhandled_exception")
