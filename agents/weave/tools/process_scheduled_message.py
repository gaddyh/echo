from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from datetime import datetime
from adapters.whatsapp.wwebjs.wwebjs_adapter import get_chat_history
from typing import Literal
from store.action_item_store import ActionItemStore
from store.scheduled_messages_store import ScheduledMessageStore
from zoneinfo import ZoneInfo
from datetime import timezone
from shared.user import get_user, RECENT_CHATS_LIMIT
from store.user import UserStore
from langchain_tavily import TavilySearch
from store.google_calendar_store import GoogleCalendarStore
from agents.weave.tools.helper import build_llm_history

tavily_search_tool = TavilySearch(
    max_results=5,
    topic="general",
)
from shared.google_calendar.token_cache import get_cached_credentials

@tool
def get_items(
    config: RunnableConfig, 
    type: Literal["scheduled_messages", "action_items"], 
    status: Literal["all", "pending", "completed"] = "pending",
    from_date: datetime = None,
    to_date: datetime = None
) -> dict:
    """
    Gets items (scheduled messages or actions) by status and/or date range.
    Returns a dict containing the result.
    If Google auth exists, action_items come from Google; otherwise from Firestore.
    """
    print(f"get_items: type: {type}, status: {status}, from_date: {from_date}, to_date: {to_date}")

    def to_utc(dt):
        try:
            return dt.replace(tzinfo=ZoneInfo("Asia/Jerusalem")).astimezone(timezone.utc)
        except Exception:
            return None

    from_date_utc = to_utc(from_date)
    to_date_utc = to_utc(to_date)

    print(f"UTC range: from {from_date_utc} to {to_date_utc}")
    user_id = config["configurable"]["user_id"]

    try:
        if type == "scheduled_messages":
            store = ScheduledMessageStore()
            return {"items": store.get_items(user_id, status, from_date_utc, to_date_utc)}

        elif type == "action_items":
            is_authed = bool(get_cached_credentials(user_id))
            if is_authed:
                store = GoogleCalendarStore()
                return {"items": store.get_items(user_id, status, from_date_utc, to_date_utc)}
            else:
                store = ActionItemStore()
                return {"items": store.get_items(user_id, status, from_date_utc, to_date_utc)}

    except Exception as e:
        print(f"get_items: failed to get items: {e}")
        return {"items": []}

@tool
async def search_chat_history(config: RunnableConfig, chat_id_to_search: str, chat_name_to_search: str, limit: int = 50) -> dict:
    """
    Search chat history by chat ID.
    Updates recent chats with the given name.
    """
    user_id = config["configurable"]["user_id"]

    if limit > 20:
        from adapters.whatsapp.wwebjs.wwebjs_adapter import send_message_from_bot
        await send_message_from_bot("מחפש בצ'אט רגע...", user_id)

    try:
        chat_history = await get_chat_history(chat_id_to_search, user_id, limit)
        transcript = build_llm_history(chat_history)
    except Exception as e:
        logging.exception(f"Failed to fetch chat history for {chat_id_to_search}")
        return {"chat_history": [], "error": str(e)}

    tryAddChatToRecentChats(user_id, chat_id_to_search, chat_name_to_search)
    print(f"search_chat_history: {chat_name_to_search} → {chat_id_to_search}")
    return {"chat_history": items}

@tool
def get_candidate_recipient_email(config: RunnableConfig, recipient_name: str) -> list:
    """
    get the candidate email of a contact.
    Returns a list of emails.
    """
    #TODO send a message to the user cause this is a long call !!
    print("get_candidate_recipient_email")
    contacts = config["configurable"]["contacts"]
    matches = [
        (name, email)
        for name, email in contacts.items()
        if recipient_name in name
    ]

    print(f"get_candidate_recipient_email: recipient_name: {recipient_name}")
    return matches

@tool
def get_candidate_recipient_chat_ids(config: RunnableConfig, recipient_name: str, isGroup: bool = False) -> list:
    """
    get the candidate chat ids of a contact.
    Returns a list of chat ids.
    """
    #TODO send a message to the user cause this is a long call !!
    print("get_candidate_recipient_chat_ids")
    name2chat_id = config["configurable"]["name2chat_id"]
    matches = [
        (name, chat_id)
        for name, chat_id in name2chat_id.items()
        if recipient_name in name
    ]

    print(f"get_candidate_recipient_chat_ids: recipient_name: {recipient_name}")
    return matches

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from phonenumbers import parse, is_valid_number, is_possible_number, NumberParseException
from context.agents.action_item import ScheduledMessageItem
from store.scheduled_messages_store import ScheduledMessageStore
import logging

def tryAddChatToRecentChats(user_id: str, recipient_chat_id: str, recipient_name: str):
    user = get_user(user_id)
    if user is None:
        return

    user.runtime.recent_chats[recipient_name] = recipient_chat_id  # Key = name, value = chat_id

    user_store = UserStore(user_id)
    user_store.save(user)


@tool(args_schema=ScheduledMessageItem)
def process_contact_message(config: RunnableConfig, **kwargs) -> dict:
    """
    Process a scheduled message to a contact.
    Returns a dict containing the created item_id.
    """
    try:
        action = ScheduledMessageItem(**kwargs)
        user_id = config["configurable"]["user_id"]
        store = ScheduledMessageStore()
        tryAddChatToRecentChats(user_id, action.recipient_chat_id, action.recipient_name)
        logging.info(f"[TOOL] Processing message for user {user_id}: {action}")

        if action.command == "create":
            item_id = store.save(user_id=user_id, item=action)
        elif action.command == "update":
            store.update(item_id=action.item_id, updates=action.model_dump())
            item_id = action.item_id
        elif action.command == "delete":
            store.delete(item_id=action.item_id)
            item_id = action.item_id

        logging.info(f"[TOOL] Message stored with item_id: {item_id}")
        return {"item_id": item_id}

    except Exception as e:
        logging.exception("[TOOL] Failed to process scheduled message.")
        return {"item_id": None}
