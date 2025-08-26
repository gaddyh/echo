# pip install websocket-client
import json
import ssl
import time
from websocket import create_connection
from green_api.instance_mng.config import GREEN_API_PARTNER_API_URL
from shared.user import get_user

def get_qr_image(user_id: str, timeout_seconds: int = 100) -> str:
    """
    Connects to Green API Scanqrcode WS and returns the first QR code image as a base64 string.
    If already authorized or timeout, raises RuntimeError.
    """
    partner_api_url = GREEN_API_PARTNER_API_URL
    user = get_user(user_id)
    if not user or not user.runtime.greenApiInstance or not user.runtime.greenApiInstance.id:
        raise RuntimeError("User not found")

    ws_url = f"wss://{partner_api_url.replace('https://', '').replace('http://', '').rstrip('/')}" \
         f"/waInstance{user.runtime.greenApiInstance.id}/scanqrcode/{user.runtime.greenApiInstance.token}"

    print("Connecting to", ws_url)
    ws = create_connection(ws_url, sslopt={"cert_reqs": ssl.CERT_NONE})
    ws.settimeout(5.0)

    start = time.time()
    try:
        while True:
            if time.time() - start > timeout_seconds:
                raise RuntimeError("QR scan timeout")

            try:
                raw = ws.recv()
            except Exception:
                time.sleep(0.2)
                continue

            evt = json.loads(raw)
            etype = evt.get("type")

            if etype == "qrCode":
                # Return only the image payload (base64 PNG string)
                return evt["message"]
            elif etype == "alreadyLogged":
                raise RuntimeError("Instance already authorized")
            elif etype in ("timeout", "error"):
                raise RuntimeError(evt.get("message", etype))
    finally:
        ws.close()
