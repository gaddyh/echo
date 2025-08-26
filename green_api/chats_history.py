# chats_history.py
# Requires: pip install requests
from typing import List, Dict, Any
import requests
from shared.user import get_user
from green_api.instance_mng.config import GREEN_API_PARTNER_API_URL

DEFAULT_COUNT = 20
MAX_COUNT = 50

def get_last_messages_for_user(user_id: str, chat_id: str, count: int = DEFAULT_COUNT) -> List[Dict[str, Any]]:
    user = get_user(user_id)
    if not user or not user.runtime.greenApiInstance or not user.runtime.greenApiInstance.id:
        raise RuntimeError("User not found")
    return _get_chat_history(
        GREEN_API_PARTNER_API_URL,
        user.runtime.greenApiInstance.id,
        user.runtime.greenApiInstance.token,
        chat_id,
        count,
    )

def _get_chat_history(
    api_url: str,
    id_instance: str,
    api_token_instance: str,
    chat_id: str,
    count: int = DEFAULT_COUNT,
    timeout: float = 20.0,
) -> List[Dict[str, Any]]:
    """
    Fetch chat history via Green API Journals.GetChatHistory.
    - count defaults to 20 and is capped at 50.
    - Returns a list of message dicts as provided by Green API.

    Endpoint:
      POST {apiUrl}/waInstance{idInstance}/GetChatHistory/{apiTokenInstance}
      Body: { "chatId": "<phone>@c.us", "count": <int> }
    """
    if api_token_instance.startswith("gac."):
        raise ValueError("Use per-instance apiTokenInstance, not partner token (gac.*).")

    # enforce limits
    if count < 1:
        count = 1
    if count > MAX_COUNT:
        count = MAX_COUNT

    url = f"{api_url.rstrip('/')}/waInstance{id_instance}/GetChatHistory/{api_token_instance}"
    payload = {"chatId": chat_id, "count": count}

    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    # Green API returns a list of messages (or empty list)
    data = r.json()
    return data if isinstance(data, list) else []


from datetime import datetime

from datetime import datetime

from collections import defaultdict, Counter
from datetime import datetime

from collections import defaultdict, Counter
from datetime import datetime

from collections import defaultdict, Counter
from datetime import datetime

def format_messages_for_llm(messages, as_string=True):
    # 1. Collect reactions by target message
    reactions_by_msg = defaultdict(list)
    for m in messages:
        if m.get("typeMessage") == "reactionMessage":
            target = m.get("stanzaId")
            emoji = m.get("reactionText")
            sender = m.get("senderName") or m.get("senderId")
            if target and emoji:
                reactions_by_msg[target].append((emoji, sender))

    summaries = []
    for m in messages:
        msg_type = m.get("typeMessage", "unknown")
        if msg_type == "reactionMessage":
            continue  # merge reactions later

        sender = "Outgoing" if m.get("type") == "outgoing" else "Incoming"
        ts = m.get("timestamp")
        time_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "unknown time"

        text = m.get("textMessage") or m.get("caption") or ""

        # Extended link preview
        if "extendedTextMessage" in m and msg_type != "quotedMessage":
            ext = m["extendedTextMessage"]
            title, desc = ext.get("title", ""), ext.get("description", "")
            if title or desc:
                text += f" [link preview: {title} — {desc}]"

        # Quoted replies (include reply text + quoted ref + quoted sender)
        if msg_type == "quotedMessage":
            reply_text = m.get("extendedTextMessage", {}).get("text", "")
            qm = m.get("quotedMessage", {})
            qtext = qm.get("textMessage") or qm.get("caption") or qm.get("typeMessage")
            qsender = qm.get("senderName") or qm.get("participant") or "unknown"
            text = f"{reply_text} [replying to: {qtext} (from {qsender})]"

        # Edited/deleted
        if m.get("isEdited"):
            text += " (edited)"
        if m.get("isDeleted"):
            text = "(deleted message)"

        # Merge reactions into original message
        reactions = reactions_by_msg.get(m.get("idMessage"))
        if reactions:
            counts = Counter([emoji for emoji, _ in reactions])
            agg = " ".join([f"{emoji}×{count}" if count > 1 else emoji for emoji, count in counts.items()])
            text += f" [{agg}]"

        summaries.append(f"{sender} {msg_type} at {time_str} — {text}".strip())

    return "\n".join(summaries) if as_string else summaries

if __name__ == "__main__":
    #res = get_last_messages_for_user("972546610653", "120363048258447119@g.us", 20)
    res = get_last_messages_for_user("972546610653", "972522486836@c.us", 20)
    print(format_messages_for_llm(res))