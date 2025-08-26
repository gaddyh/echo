import asyncio
from langgraph.prebuilt import create_react_agent
from dotenv import load_dotenv
from agents.action.prompt import ACTION_PROMPT
from agents.action.tools.process_action_item import process_action_item
from agents.action.tools.process_scheduled_message import process_scheduled_message, get_chat_id
from shared.user import checkpointer
from shared import time

load_dotenv(".venv/.env")

def create_agent():
    return create_react_agent(
        model="gpt-4.1",
        tools=[process_action_item, process_scheduled_message, get_chat_id],
        prompt=ACTION_PROMPT,
        checkpointer=checkpointer,
        #response_format=ActionItemResponse
    )

actionAgent = create_agent()