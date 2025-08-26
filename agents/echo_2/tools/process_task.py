
from context.agents.task_item import TaskItem
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

@tool(args_schema=TaskItem)
def process_task(config: RunnableConfig, **kwargs) -> dict:
    """
    Process an action item (reminder, task, or event).
    Firestore-only MVP.
    Returns: { ok: bool, item_id: str|None, error: str|None, code: str|None }
    """