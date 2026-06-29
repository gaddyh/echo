from assistant.schemas import TaskItem
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from shared.observability.metrics import track_tool_call
import time as pytime


@tool(args_schema=TaskItem)
def process_task(config: RunnableConfig, **kwargs) -> dict:
    """
    Create, update, or delete a task.
    Returns: { ok: bool, item_id: str|None, error: str|None, code: str|None }
    """
    start = pytime.time()
    user_id = config["configurable"].get("user_id", "unknown")
    try:
        scheduling = config["configurable"]["scheduling"]
        result = scheduling.upsert_task(
            user_id,
            kwargs["command"],
            item_id=kwargs.get("item_id"),
            title=kwargs.get("title"),
            description=kwargs.get("description"),
            dt=kwargs.get("datetime"),
            due=kwargs.get("due"),
            completed=kwargs.get("completed"),
            list_id=kwargs.get("list_id"),
            parent_id=kwargs.get("parent_id"),
            position=kwargs.get("position"),
            status=kwargs.get("status"),
            op_id=kwargs.get("op_id"),
        )
        ok_val = 1 if result.get("ok") else 0
        track_tool_call(user_id=user_id, tool="process_task",
                        op=kwargs.get("command", "unknown"), item_type="task",
                        ok=ok_val, latency_ms=int((pytime.time() - start) * 1000),
                        error_code=result.get("code") if not ok_val else None)
        return result
    except Exception as e:
        print("process_task error:", e)
        track_tool_call(user_id=user_id, tool="process_task",
                        op=kwargs.get("command", "unknown"), item_type="task",
                        ok=0, latency_ms=int((pytime.time() - start) * 1000),
                        error_code="internal_error")
        return {"ok": False, "item_id": None, "error": str(e), "code": "internal_error"}