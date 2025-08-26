from typing import Optional, Union
from datetime import datetime
import time as pytime

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig

from store.action_item_store import ActionItemStore
from context.agents.action_item import ActionItem
from shared.observability.metrics import track_tool_call

def _fail(msg: str, code: Optional[str] = None):
    return {"ok": False, "item_id": None, "error": msg, "code": code or "bad_request"}

def _ok(item_id: Optional[str]):
    return {"ok": True, "item_id": item_id, "error": None, "code": None}

def _normalize_dt_to_str(dt: Optional[Union[str, datetime]]) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt.strip() or None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return None

def _validate(action: ActionItem):
    if action.command not in ("create", "update", "delete"):
        return "unknown_command"
    if action.command == "create":
        if not action.title:
            return "missing_title"
        if not getattr(action, "datetime", None):
            return "missing_datetime"
    if action.command in ("update", "delete") and not action.item_id:
        return "missing_item_id"
    return None

@tool(args_schema=ActionItem)
def process_self_action(config: RunnableConfig, **kwargs) -> dict:
    """
    Process an action item (reminder, task, or event).
    Firestore-only MVP.
    Returns: { ok: bool, item_id: str|None, error: str|None, code: str|None }
    """
    start = pytime.time()
    try:
        action = ActionItem(**kwargs)
        user_id = config["configurable"]["user_id"]
        store = ActionItemStore()

        err = _validate(action)
        if err:
            latency_ms = int((pytime.time() - start) * 1000)
            track_tool_call(user_id=user_id, tool="process_self_action",
                            op=action.command, item_type=action.item_type,
                            ok=0, latency_ms=latency_ms, error_code=err)
            return _fail(err)

        dt_str = _normalize_dt_to_str(getattr(action, "datetime", None))
        op_id = getattr(action, "op_id", None)  # <-- use if present

        if action.command == "create":
            item_id = store.create_action_item(
                user_id=user_id,
                item_type=action.item_type,
                title=action.title,
                description=action.description,
                dt=dt_str,
                location=action.location,
                op_id=op_id,   # <-- pass through
            )
            latency_ms = int((pytime.time() - start) * 1000)
            track_tool_call(user_id=user_id, tool="process_self_action",
                            op="create", item_type=action.item_type,
                            ok=1, latency_ms=latency_ms)
            return _ok(item_id)

        if action.command == "update":
            updated = store.update_action_item(
                user_id=user_id,
                item_id=action.item_id,
                item_type=action.item_type,
                title=action.title,
                description=action.description,
                dt=dt_str,
                location=action.location,
                status=action.status,
            )
            latency_ms = int((pytime.time() - start) * 1000)
            track_tool_call(user_id=user_id, tool="process_self_action",
                            op="update", item_type=action.item_type,
                            ok=1 if updated else 0, latency_ms=latency_ms,
                            error_code=None if updated else "not_found")
            if not updated:
                return _fail("not_found", code="not_found")
            return _ok(action.item_id)

        if action.command == "delete":
            deleted = store.delete_action_item(user_id=user_id, item_id=action.item_id)
            latency_ms = int((pytime.time() - start) * 1000)
            track_tool_call(user_id=user_id, tool="process_self_action",
                            op="delete", item_type=action.item_type,
                            ok=1 if deleted else 0, latency_ms=latency_ms,
                            error_code=None if deleted else "not_found")
            if not deleted:
                return _fail("not_found", code="not_found")
            return _ok(action.item_id)

        latency_ms = int((pytime.time() - start) * 1000)
        track_tool_call(user_id=user_id, tool="process_self_action",
                        op=action.command, item_type=action.item_type,
                        ok=0, latency_ms=latency_ms, error_code="unknown_command")
        return _fail("unknown_command")

    except Exception as e:
        latency_ms = int((pytime.time() - start) * 1000)
        print("process_self_action error:", e)
        track_tool_call(user_id=config["configurable"].get("user_id", "unknown"),
                        tool="process_self_action",
                        op=kwargs.get("command", "unknown"),
                        item_type=kwargs.get("item_type"),
                        ok=0, latency_ms=latency_ms, error_code="internal_error")
        return _fail("unhandled_exception", code="internal_error")
