import requests
from shared.user import get_user
from green_api.instance_mng.config import GREEN_API_PARTNER_API_URL

def get_all_contacts(user_id: str):
    user = get_user(user_id)
    if not user or not user.runtime.greenApiInstance or not user.runtime.greenApiInstance.id:
        raise RuntimeError("User not found")
    contacts = _get_contacts(
        user.runtime.greenApiInstance.id,
        user.runtime.greenApiInstance.token,
    )
    return contacts_to_name_ids(contacts)

from typing import Dict

from collections import defaultdict
from typing import Dict, List, Iterable, Mapping, Any

def contacts_to_name_ids(contacts: Iterable[Mapping[str, Any]]) -> Dict[str, List[str]]:
    """
    Build name -> [id,...] mapping from GreenAPI GetContacts items.
    Rules:
    - use 'name' if present
    - use 'contactName' if present
    - if both present and equal -> keep once
    - if both present and different -> add both (each maps to same id)
    - if the same name appears for multiple ids -> keep all ids
    """
    result: defaultdict[str, set[str]] = defaultdict(set)

    for c in contacts:
        chat_id = (c.get("id") or "").strip()
        if not chat_id:
            continue

        name = (c.get("name") or "").strip()
        contact_name = (c.get("contactName") or "").strip()

        names: list[str] = []
        if name:
            names.append(name)
        if contact_name and contact_name not in names:
            names.append(contact_name)

        for n in names:
            result[n].add(chat_id)

    # convert sets to lists (stable-ish order)
    return {n: sorted(ids) for n, ids in result.items()}

def _get_contacts(id_instance: str, api_token_instance: str):
    url = f"{GREEN_API_PARTNER_API_URL.rstrip('/')}/waInstance{id_instance}/GetContacts/{api_token_instance}"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()

def get_contact_info(user_id: str, chat_id: str):
    user = get_user(user_id)
    if not user or not user.runtime.greenApiInstance or not user.runtime.greenApiInstance.id:
        raise RuntimeError("User not found")
    return _get_contact_info(
        user.runtime.greenApiInstance.id,
        user.runtime.greenApiInstance.token,
        chat_id,
    )

def _get_contact_info(id_instance: str, api_token_instance: str, chat_id: str):
    url = f"{GREEN_API_PARTNER_API_URL.rstrip('/')}/waInstance{id_instance}/GetContactInfo/{api_token_instance}"
    r = requests.post(url, json={"chatId": chat_id}, timeout=15)
    r.raise_for_status()
    return r.json()

if __name__ == "__main__":
    print(contacts_to_name_id(get_all_contacts("972546610653")))
