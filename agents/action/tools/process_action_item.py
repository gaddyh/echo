from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from store.action_item_store import ActionItemStore
from context.agents.action_item import ActionItem

@tool(args_schema=ActionItem)
def process_action_item(config: RunnableConfig, **kwargs) -> dict:
    """
    process an action item (reminder, task, or event).
    Returns a dict containing the created item_id.
    """

    action = ActionItem(**kwargs)
    print("process_action_item action: ", action)
    user_id = config["configurable"]["user_id"]
    store = ActionItemStore()
    if action.command == "create":
        item_id = store.create_action_item(user_id, action.item_type, action.title, action.description, action.datetime, action.location)
    elif action.command == "update":
        store.update_action_item(user_id, action.item_id, action.item_type, action.title, action.description, action.datetime, action.location, action.status)
        item_id = action.item_id
    elif action.command == "delete":
        store.delete_action_item(user_id, action.item_id)
        item_id = action.item_id
    return {"item_id": item_id}
