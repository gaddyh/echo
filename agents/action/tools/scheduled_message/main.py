
from shared import time
import uuid
import asyncio
import time as pytime
from shared.result import getAgentMessage
from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from context.scheduled_message import ScheduledMessage
scheduled_message_agent = "dfdf"

@tool
def process_scheduled_message(config: RunnableConfig, messageToSend: str, contactNumber: str) -> dict:
    """
    process a scheduled message to a contact.
    Returns a dict containing the created item_id.
    """

    print("process_scheduled_message action: ", messageToSend, contactNumber)
    user_id = config["configurable"]["user_id"]
    return {"item_id": "123"}

async def scheduled_message(userMessage: str, config: dict):
    input = {"messages":[
        {"content": userMessage, "role": "user"},
        {"content": f"now is {time.to_user_timezone(time.utcnow()).strftime('%Y-%m-%d %H:%M:%S')}", "role": "system"}
    ]}
    return await scheduled_message_agent.ainvoke(input, config)