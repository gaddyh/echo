# Requires: pip install requests
from typing import List, Dict, Any
import requests
from shared.user import get_user
from green_api.instance_mng.config import GREEN_API_PARTNER_API_URL
def _names_from_contact(contact: Dict[str, Any]) -> List[str]:
    name = (contact.get("name") or "").strip()
    contact_name = (contact.get("contactName") or "").strip()
    out: List[str] = []
    if name:
        out.append(name)
    if contact_name and contact_name not in out:
        out.append(contact_name)
    return out


def _get_contacts(id_instance: str, api_token_instance: str, timeout: float = 20.0) -> List[Dict[str, Any]]:
    """GET all contacts (users + groups)."""
    url = f"{GREEN_API_PARTNER_API_URL.rstrip('/')}/waInstance{id_instance}/GetContacts/{api_token_instance}"
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _get_group_data(id_instance: str, api_token_instance: str, group_id: str, timeout: float = 20.0) -> Dict[str, Any]:
    """POST get group data (participants, etc.)."""
    url = f"{GREEN_API_PARTNER_API_URL.rstrip('/')}/waInstance{id_instance}/GetGroupData/{api_token_instance}"
    r = requests.post(url, json={"groupId": group_id}, timeout=timeout)
    r.raise_for_status()
    return r.json() or {}


def _get_contact_info(id_instance: str, api_token_instance: str, chat_id: str, timeout: float = 15.0) -> Dict[str, Any]:
    """POST get single contact info (fallback when not in cache)."""
    url = f"{GREEN_API_PARTNER_API_URL.rstrip('/')}/waInstance{id_instance}/GetContactInfo/{api_token_instance}"
    r = requests.post(url, json={"chatId": chat_id}, timeout=timeout)
    r.raise_for_status()
    return r.json() or {}

def list_groups(user_id: str, timeout: float = 20.0) -> List[Dict[str, Any]]:
    user = get_user(user_id)
    if not user or not user.runtime.greenApiInstance or not user.runtime.greenApiInstance.id:
        raise RuntimeError("User not found")
    return _list_groups(
        user.runtime.greenApiInstance.id,
        user.runtime.greenApiInstance.token,
        timeout=timeout,
    )

def _list_groups(
    id_instance: str,
    api_token_instance: str,
    timeout: float = 20.0,
) -> List[Dict[str, Any]]:
    """
    Returns:
    [
      {
        "group_name": "<name>",
        "group_id": "<id@g.us>",
      },
      ...
    ]
    """
    if api_token_instance.startswith("gac."):
        raise ValueError("Use per-instance apiTokenInstance, not partner token (gac.*).")

    contacts = _get_contacts(id_instance, api_token_instance, timeout=timeout)

    groups = [c for c in contacts if isinstance(c, dict) and c.get("type") == "group"]

    results: List[Dict[str, Any]] = []

    for g in groups:
        gid = g.get("id")
        gname = (g.get("name") or "").strip()
        if not gid or not gname:
            continue

        results.append(
            {
                "group_name": gname,
                "group_id": gid,
            }
        )

    return results

if __name__ == "__main__":
    data = list_groups("972546610653")

    for g in data:
        print(g["group_name"], g["group_id"])

