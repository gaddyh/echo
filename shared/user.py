from store.user import UserStore
from dotenv import load_dotenv
from shared.time import utcnow
import os
from context.user import userContextDict, User, UserConfig, UserRuntime, TokenUsage
from store.chat_index import UserChatIndexStore
from context.windowed_InMemorySaver import WindowedInMemorySaver
from db.base import db

load_dotenv(".venv/.env")

# cpu 0 - echo, 
# cpu 1-2 shared
cpu_count = 11  # num cpus - 1

NODE_URL = os.getenv("NODE_URL", "http://localhost:3000")
RECENT_CHATS_LIMIT = 25
checkpointer = WindowedInMemorySaver(window_size=30) # keep last 30 messages, 15 interactions


def get_index(user_id):
    if user_id == "972552534936":
        return 0
    return 1 + int(user_id) % cpu_count

def getUserIds():
    users_ref = db.collection("users")
    docs = users_ref.stream()
    return [doc.id for doc in docs]

def ensure_current_month_token_usage(user: User) -> None:
    current_month = utcnow().strftime("%Y-%m")
    usage = user.runtime.monthlyTokenUsage
    if current_month not in usage:
        usage[current_month] = TokenUsage()
        UserStore(user.user_id).save(user)


def get_user(user_id: str) -> User | None:
    user = userContextDict.get(user_id)
    if user is None and "972" not in user_id:
        user_id = "972" + user_id[1:]
        user = userContextDict.get(user_id)

    if user is None:
        user_store = UserStore(user_id)
        user = user_store.load()

    if user:
        ensure_current_month_token_usage(user)

    return user


def create_user(user_id: str, message: str, sender_name: str = "", actionAgentChatId: str = "") -> User | None:
    index = get_index(user_id)

    userConfig = UserConfig(
        name=sender_name,
        timezone="Asia/Jerusalem",
        language="he",
        preferences={
            "nudge_minutes_before": None,
            "followup_minutes_after": None
        }
    )

    runtime = UserRuntime(
        monthlyTokenUsage={
            utcnow().strftime("%Y-%m"): TokenUsage(total=0)
        },
        deploymentUrl=NODE_URL + '/' + str(index),
        actionAgentChatId=actionAgentChatId,
        green_api_contacts={}
    )

    user = User(
        user_id=user_id,
        config=userConfig,
        runtime=runtime
    )
    user_store = UserStore(user_id)
    user_store.save(user)

    return user


def get_node_url(user_id):
    user = get_user(user_id)
    if user:
        return user.runtime.deploymentUrl

    return NODE_URL + '/' + str(get_index(user_id))


from typing import Dict, Any, List, Tuple

def build_name_to_chat_id(
    green_api_contacts: List[Dict[str, Any]],
    new_contact: Dict[str, Any] = None,
) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """
    Returns:
      - name_to_chat_id: {display_name -> chat_id}
      - collisions: {display_name -> [chat_id, ...]}  # only if same name appears multiple times
    """
    name_to_chat_id: Dict[str, str] = {}
    collisions: Dict[str, List[str]] = {}

    def _add(name: str, chat_id: str) -> None:
        if not name or not chat_id:
            return
        key = name.strip()
        if key in name_to_chat_id and name_to_chat_id[key] != chat_id:
            # track duplicates without losing data
            arr = collisions.setdefault(key, [])
            if name_to_chat_id[key] not in arr:
                arr.append(name_to_chat_id[key])
            if chat_id not in arr:
                arr.append(chat_id)
        else:
            name_to_chat_id[key] = chat_id

    # contacts
    for c in green_api_contacts or []:
        chat_id = c.get("id")
        name = c.get("name") or c.get("pushname") or chat_id
        _add(name, chat_id)

    return name_to_chat_id, collisions

# recent_map.py
from typing import Dict, Any, List, Tuple
from collections import defaultdict

# ---- Build a lookup of chat_id -> best display name ----
# shared/user.py

from typing import Any, Dict, List

def build_chatid_to_name(contacts: Any) -> Dict[str, str]:
    """
    Returns { chatId: name }.

    Accepts:
      - List[{"id": str, "name": str}]               (GreenAPI-style items)
      - List[{"id": str, "name": str, "contactName": str}]  (use 'name' then fallback)
      - List[{name: id}]                              (singleton dict)
      - Dict[name, id]                                (single id)
      - Dict[name, Iterable[id]]                      (multiple ids per name)

    Ignores invalid entries. If a chat_id appears multiple times with different names,
    keeps the first non-empty name seen for stability.
    """
    mapping: Dict[str, str] = {}

    # Dict[name -> id or iterable[id]]
    if isinstance(contacts, dict):
        for name, cid_or_iter in contacts.items():
            if not isinstance(name, str) or not name.strip():
                continue
            name_s = name.strip()

            if isinstance(cid_or_iter, str):
                cid = cid_or_iter.strip()
                if cid:
                    mapping.setdefault(cid, name_s)
            elif isinstance(cid_or_iter, (list, set, tuple)):
                for cid in cid_or_iter:
                    if isinstance(cid, str) and cid.strip():
                        mapping.setdefault(cid.strip(), name_s)
        return mapping

    # List[…]
    if isinstance(contacts, list):
        for c in contacts:
            if not isinstance(c, dict):
                continue

            if "id" in c:
                cid = (c.get("id") or "").strip()
                # prefer 'name' over 'contactName' if both exist
                name = (c.get("name") or c.get("contactName") or "").strip()
                if cid and name:
                    mapping.setdefault(cid, name)
                continue

            # singleton {name: id}
            if len(c) == 1:
                (name, cid), = c.items()
                if isinstance(name, str) and isinstance(cid, str):
                    name_s, cid_s = name.strip(), cid.strip()
                    if name_s and cid_s:
                        mapping.setdefault(cid_s, name_s)
        return mapping

    return mapping


def normalize_phone(number: str) -> str:
    """
    Normalize a phone number to E.164 without the leading '+'.
    Example: '+972546610655' -> '972546610655'
    """
    return number.lstrip('+').strip()