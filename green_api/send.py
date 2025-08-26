# pip install requests
import requests
from green_api.instance_mng.config import GREEN_API_PARTNER_API_URL
from shared.user import get_user

def send_message_from_me(user_id: str, chat_id: str, message: str):
    user = get_user(user_id)
    if not user or not user.runtime.greenApiInstance or not user.runtime.greenApiInstance.id:
        raise RuntimeError("User not found")
    return send_message(
        user.runtime.greenApiInstance.id,
        user.runtime.greenApiInstance.token,
        chat_id,
        message,
    )

def send_message(
    id_instance: str,
    api_token_instance: str,
    chat_id: str,
    message: str,
    quoted_message_id: str | None = None,
    link_preview: bool | None = None,
    type_preview: str | None = None,   # 'large' | 'small'
    custom_preview: dict | None = None,
    typing_time_ms: int | None = None, # 1000..20000
    timeout: float = 15.0,
) -> str:
    """
    Returns idMessage on success.
    Raises HTTPError on non-2xx or ValueError on empty id.
    """
    if api_token_instance.startswith("gac."):
        raise ValueError("Use apiTokenInstance (per-instance), not partner token (gac.*)")

    url = f"{GREEN_API_PARTNER_API_URL.rstrip('/')}/waInstance{id_instance}/sendMessage/{api_token_instance}"
    payload = {"chatId": chat_id, "message": message}
    if quoted_message_id is not None:
        payload["quotedMessageId"] = quoted_message_id
    if link_preview is not None:
        payload["linkPreview"] = link_preview
    if type_preview is not None:
        payload["typePreview"] = type_preview
    if custom_preview is not None:
        payload["customPreview"] = custom_preview
    if typing_time_ms is not None:
        payload["typingTime"] = typing_time_ms

    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    data = r.json() if r.content else {}
    msg_id = data.get("idMessage")
    if not msg_id:
        raise ValueError(f"Missing idMessage in response: {data}")
    return msg_id

if __name__ == "__main__":
    send_message_from_me("972546610653", "972546610653@c.us", "hello")