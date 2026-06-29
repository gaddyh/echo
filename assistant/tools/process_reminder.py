from assistant.schemas import ReminderItem
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from shared.observability.metrics import track_tool_call
import time as pytime


@tool(args_schema=ReminderItem)
def process_reminder(config: RunnableConfig, **kwargs) -> dict:
    """
    Create, update, or delete a reminder.
    Returns: { ok: bool, item_id: str|None, error: str|None, code: str|None }
    """
    start = pytime.time()
    user_id = config["configurable"].get("user_id", "unknown")
    try:
        scheduling = config["configurable"]["scheduling"]
        result = scheduling.upsert_reminder(
            user_id,
            kwargs["command"],
            item_id=kwargs.get("item_id"),
            title=kwargs.get("title"),
            description=kwargs.get("description"),
            dt=kwargs.get("datetime"),
            status=kwargs.get("status"),
            op_id=kwargs.get("op_id"),
        )
        ok_val = 1 if result.get("ok") else 0
        track_tool_call(user_id=user_id, tool="process_reminder",
                        op=kwargs.get("command", "unknown"), item_type="reminder",
                        ok=ok_val, latency_ms=int((pytime.time() - start) * 1000),
                        error_code=result.get("code") if not ok_val else None)
        return result
    except Exception as e:
        print("process_reminder error:", e)
        track_tool_call(user_id=user_id, tool="process_reminder",
                        op=kwargs.get("command", "unknown"), item_type="reminder",
                        ok=0, latency_ms=int((pytime.time() - start) * 1000),
                        error_code="internal_error")
        return {"ok": False, "item_id": None, "error": str(e), "code": "internal_error"}