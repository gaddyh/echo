from langchain.tools import tool
from langchain_core.runnables import RunnableConfig


@tool
def get_chat_id(config: RunnableConfig, name: str) -> dict:
    """
    get the chat id of a contact.
    Returns a dict containing the chat id.
    """

    print("get_chat_id action: ", name)
    user_id = config["configurable"]["user_id"]
    return {"chat_id": "123"}

@tool
def process_scheduled_message(config: RunnableConfig, messageToSend: str, chat_id: str) -> dict:
    """
    process a scheduled message to a contact.
    Returns a dict containing the created item_id.
    """

    print("process_scheduled_message action: ", messageToSend, chat_id)
    user_id = config["configurable"]["user_id"]
    return {"item_id": "123"}