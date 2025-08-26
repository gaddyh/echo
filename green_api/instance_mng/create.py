import requests
from context.user import GreenApiInstance
from green_api.instance_mng.config import GREEN_API_PARTNER_API_URL, GREEN_API_PARTNER_TOKEN

def pool_create_instance():
    """
    Create a pool instance (not tied to a user yet).
    Returns dict with id/token for storage in Firestore.
    """
    url = f"{GREEN_API_PARTNER_API_URL.rstrip('/')}/partner/createInstance/{GREEN_API_PARTNER_TOKEN}"

    payload = {
        "name": "Echo - qr ready pool",
        "delaySendMessagesMilliseconds": 3000,
        "outgoingAPIMessageWebhook": "yes",
        "outgoingWebhook": "yes",
        "outgoingMessageWebhook": "yes",
        "incomingWebhook": "yes",
    }

    response = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
    data = response.json()
    if response.status_code == 200 and "idInstance" in data and "apiTokenInstance" in data:
        return data["idInstance"], data["apiTokenInstance"]
    else:
        raise RuntimeError(f"Failed to create pool instance: {data}")
