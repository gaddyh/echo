import hmac
import hashlib
import json
import os

APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "your_app_secret")

# This should be exactly the JSON body you plan to send in Postman
payload = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "WHATSAPP_BUSINESS_ID",
            "changes": [
                {
                    "value": {
                        "messages": [
                            {
                                "from": "441234567890",
                                "id": "wamid.HBgLMzYzNzk0NTg1NzU1FQIAEhggQ0ZFNT...",
                                "timestamp": "1682178800",
                                "type": "text",
                                "text": {"body": "hello"}
                            }
                        ],
                        "metadata": {
                            "display_phone_number": "1234567890",
                            "phone_number_id": "PHONE_NUMBER_ID"
                        }
                    },
                    "field": "messages"
                }
            ]
        }
    ]
}

# Convert the payload to a JSON string, then to bytes
body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

# Generate HMAC SHA256 signature
signature = hmac.new(APP_SECRET.encode(), body_bytes, hashlib.sha256).hexdigest()

# Final header value
print("X-Hub-Signature-256:", f"sha256={signature}")
