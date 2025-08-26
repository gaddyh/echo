import os
import hmac
import hashlib
import logging
import asyncio
import contextlib

from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import (
    FastAPI,
    Request,
    HTTPException,
    Response,
    Header,
    Depends,
    Query,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ValidationError

from agents.main import handleUserInput
from shared.observability.tracing import Tracer
from shared.event_trigger import trigger_events_loop
from context.chat_metadata import GroupMetadataPayload  # noqa: F401 (kept for compatibility)
from store.chat_index import UserChatIndexStore  # noqa: F401 (kept for compatibility)
from adapters.whatsapp.wwebjs.wwebjs_adapter import (
    init_message_context,  # noqa: F401
    save_audio_base64_to_file,
    send_message_to_bot,
    send_message_from_bot,  # noqa: F401
)
from shared.user import get_user, create_user
from context.message.raw_message import WhatsAppMessage, bot_registry
from shared.google_tts import transcribe_opus_file
from shared.user import get_node_url, RECENT_CHATS_LIMIT
from store.user import UserStore
from adapters.whatsapp.dialog360.webhook import dialog360_router
from shared.google_calendar.oauth import google_router
from shared.google_calendar.calendar import calendar_router, contacts_router
from adapters.whatsapp.cloudapi.cloud_api_adapter import CloudAPIAdapter
from db.base import db

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# -----------------------------------------------------------------------------
# App lifecycle: background events loop
# -----------------------------------------------------------------------------
running = True


import os, time, asyncio, contextlib, logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

CONTACTS_REFRESH_SEC = int(os.getenv("CONTACTS_REFRESH_SEC", "3600"))  # 1 hour default

async def contacts_reload_loop(interval_sec: int, stop: asyncio.Event):
    """Run refresh_contacts() every `interval_sec` until `stop` is set."""
    while not stop.is_set():
        t0 = time.perf_counter()
        try:
            # refresh_contacts is sync; run in a worker thread
            await asyncio.to_thread(refresh_contacts)
        except Exception:
            logging.exception("refresh_contacts failed")
        # sleep the remainder (cancellable)
        remaining = interval_sec - (time.perf_counter() - t0)
        try:
            await asyncio.wait_for(stop.wait(), timeout=max(0, remaining))
        except asyncio.TimeoutError:
            pass  # time to run the next cycle

from contextlib import asynccontextmanager
from fastapi import FastAPI
from google.cloud import firestore
import asyncio, datetime
from green_api.instance_mng.create import pool_create_instance

POOL_SIZE = 1
async def ensure_pool_ready():
    pool_ref = db.collection("instances_pool")

    docs = [doc for doc in pool_ref.limit(POOL_SIZE).stream()]
    ready_count = len(docs)

    if ready_count < POOL_SIZE:
        needed = POOL_SIZE - ready_count
        for _ in range(needed):
            idInstance, apiTokenInstance = pool_create_instance()
            idInstance = str(idInstance)
            pool_ref.document(idInstance).set({
                "idInstance": idInstance,
                "apiTokenInstance": apiTokenInstance,
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            })
        print(f"✨ Added {needed} new instance(s) to pool")

async def pool_worker(stop_event: asyncio.Event):
    """Runs forever until stop_event is set."""
    while not stop_event.is_set():
        try:
            await ensure_pool_ready()
        except Exception as e:
            print("Pool worker error:", e)
        await asyncio.sleep(60)  # run every 60s


@asynccontextmanager
async def lifespan(app: FastAPI):
    # existing
    running = True
    stop_event = asyncio.Event()

    loop_task = asyncio.create_task(trigger_events_loop())  # your existing loop
    #contacts_task = asyncio.create_task(contacts_reload_loop(CONTACTS_REFRESH_SEC, stop_event))
    worker_task = asyncio.create_task(pool_worker(stop_event))

    try:
        yield
    finally:
        # graceful shutdown
        running = False
        stop_event.set()
        for task in (loop_task, worker_task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "...")
APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")
NODE_URL = os.getenv("NODE_URL", "http://localhost:3000")

#app = FastAPI(lifespan=lifespan) TODO
app = FastAPI()
app.include_router(dialog360_router)
app.include_router(google_router)
app.include_router(calendar_router)
app.include_router(contacts_router)

templates = Jinja2Templates(directory="apps/templates")

class RegisterBotRequest(BaseModel):
    node_url: str
    users: list[str]

# -----------------------------------------------------------------------------
# Auth helpers
# -----------------------------------------------------------------------------
def verify_token(request: Request):
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    token = auth.split(" ")[1]
    if token != os.getenv("WHATSAPP_APP_SECRET"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token")

def get_bearer_headers():
    return {
        "Authorization": f"Bearer {APP_SECRET}"
    }

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.post("/register_bot")
async def register_bot(data: RegisterBotRequest, _: None = Depends(verify_token)):
    for user_id in data.users:
        bot_registry[user_id] = data.node_url
        print(f"✅ Registered {user_id} on {data.node_url}")
    return {"status": "ok", "registered_users": len(data.users)}


@app.get("/login", response_class=HTMLResponse)
async def serve_login_page(request: Request, user_id: Optional[str] = Query(None)):
    """
    Dedicated login page that contains the phone input, login button, spinner, and QR <img>.
    Make sure apps/templates/login.html exists and uses the IDs: phone, login-btn, spinner, qr-image.
    """
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "user_id": user_id}
    )


@app.get("/success")
def oauth_success():
    return HTMLResponse("<h1>✅ Google account connected!</h1>")


@app.head("/")
def head_root():
    return Response(status_code=200)


@app.get("/", response_class=HTMLResponse)
@app.get("/home", response_class=HTMLResponse)
async def home(request: Request, user_id: Optional[str] = Query(None)):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "user_id": user_id},
    )


@app.get("/contact", response_class=HTMLResponse)
async def contact(request: Request):
    return templates.TemplateResponse("contact.html", {"request": request})


@app.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    return templates.TemplateResponse("privacy.html", {"request": request})


@app.get("/terms", response_class=HTMLResponse)
async def terms(request: Request):
    return templates.TemplateResponse("terms.html", {"request": request})


# Backward-compatibility proxy for legacy node flow (optional to keep)
@app.post("/start-login")
async def start_login(req: Request):
    data = await req.json()
    async with httpx.AsyncClient() as client:
        target = f"{get_node_url(data['user_id'])}/start-login"
        print("→ proxy to:", target)  # should be http://127.0.0.1:3000/start-login (or shard port)
        resp = await client.post(target, json=data, headers=get_bearer_headers())
    return resp.json()

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.requests import Request
import uuid
import traceback

ERROR_INVALID_USER_ID = "INVALID_USER_ID"
ERROR_CHANNEL_CREATE   = "CHANNEL_CREATE_ERROR"
ERROR_LOGIN_USER       = "LOGIN_USER_ERROR"
ERROR_UNEXPECTED       = "UNEXPECTED_ERROR"

def _err(status: int, code: str, message: str, extra: dict | None = None) -> JSONResponse:
    payload = {"ok": False, "error": {"code": code, "message": message}}
    if extra:
        payload["error"].update(extra)
    return JSONResponse(status_code=status, content=payload)

def _ok(data: dict) -> JSONResponse:
    return JSONResponse(status_code=200, content={"ok": True, "data": data})

from green_api.instance_mng.qr import get_qr_image
from green_api.instance_mng.pool import claim_instance, release_instance
from db.base import db
from context.user import userContextDict
from shared.user import get_user, create_user
from green_api.instance_mng.config import GREEN_API_PARTNER_API_URL, GREEN_API_PARTNER_TOKEN
from green_api.instance_mng.create import GreenApiInstance

from fastapi import Request
from fastapi.responses import JSONResponse
import uuid, traceback

from fastapi.responses import JSONResponse

from whatsapp_api_client_python import API
from fastapi.responses import JSONResponse

@app.post("/login-user")
async def login_user(req: Request):
    try:
        data = await req.json()
    except Exception:
        return _err(400, ERROR_UNEXPECTED, "Invalid JSON payload")

    user_id = (data.get("user_id") or "").strip()
    if not (user_id.isdigit() and user_id.startswith("972") and len(user_id) == 12):
        return _err(422, ERROR_INVALID_USER_ID, "Invalid user_id format. Expecting 972XXXXXXXXX")

    inst = None
    success = False
    state = None
    token = None
    qr = None
    status = "pending"

    try:
        user = get_user(user_id)

        if user and user.runtime and user.runtime.greenApiInstance and user.runtime.greenApiInstance.token:
            token = user.runtime.greenApiInstance.token
            # Check current state
            state = get_instance_state(user_id)
            if state == "authorized":
                status = "connected"
                success = True
                return JSONResponse({
                    "status": status,
                    "token": token,
                    "qr": None,
                    "state": state
                })
            # else: fall through → try to fetch QR
        else:
            inst = claim_instance(user_id)
            token = inst["apiTokenInstance"]

        # Try QR fetch
        try:
            qr = get_qr_image(user_id)
            status = "ready"
        except Exception:
            status = "pending"

        # Cache user in memory
        user = get_user(user_id)
        if user:
            userContextDict[user_id] = user

        success = True
        return JSONResponse({
            "status": status,
            "token": token,
            "qr": qr,
            "state": state
        })

    except RuntimeError as e:
        if "No ready instance" in str(e):
            return JSONResponse({
                "status": "pending",
                "token": None,
                "qr": None,
                "state": None
            })
        raise

    except HTTPException as e:
        msg = e.detail if isinstance(e.detail, str) else str(e.detail)
        return _err(e.status_code, ERROR_UNEXPECTED, msg)

    except Exception as e:
        trace_id = str(uuid.uuid4())[:8]
        print(f"[{trace_id}] unexpected error in /login-user: {e}\n{traceback.format_exc()}")
        return _err(500, ERROR_UNEXPECTED, "Unexpected error during login", {"trace_id": trace_id})

    finally:
        if inst and not success:
            try:
                release_instance(user_id, inst)
                print(f"Released instance for {user_id} after login failure")
            except Exception as cleanup_err:
                print(f"⚠️ Failed to release instance for {user_id}: {cleanup_err}")


def get_instance_state(user_id: str) -> str:
    user = get_user(user_id)
    if not user or not getattr(user, "runtime", None) or not user.runtime.greenApiInstance:
        raise HTTPException(404, "No instance found for user")

    green = API.GreenAPI(str(user.runtime.greenApiInstance.id),
                         user.runtime.greenApiInstance.token)
    resp = green.account.getStateInstance()
    return resp.data.get("stateInstance") if hasattr(resp, "data") else resp.get("stateInstance")


@app.get("/instance-state")
async def instance_state(user_id: str):
    try:
        state = get_instance_state(user_id)
        return {"state": state}
    except HTTPException:
        # Preserve 404 from get_instance_state
        raise
    except Exception as e:
        trace_id = str(uuid.uuid4())[:8]
        print(f"[{trace_id}] error in /instance-state for {user_id}: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"Error checking instance state (trace_id={trace_id})")

from fastapi import BackgroundTasks

@app.get("/refresh-contact")
async def do_refresh_contacts(user_id: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(refresh_contact, user_id)
    adapter = CloudAPIAdapter()
    await adapter.send_template_360dialog(user_id, "welcome")
    return {"status": "ok"}

# Legacy proxy endpoints kept for compatibility (node-managed flow)
@app.get("/qr/{phone}")
async def get_qr(phone: str):
    print(f"🔍 Received QR request for {phone}")
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{get_node_url(phone)}/qr/{phone}", headers=get_bearer_headers())
    return resp.json()


@app.delete("/delete-user/{phone}")
async def delete_user(phone: str):
    print(f"🔍 Received delete request for {phone}")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{get_node_url(phone)}/delete-user/{phone}",
                headers=get_bearer_headers()
            )
        # Preserve upstream status code
        return JSONResponse(resp.json(), status_code=resp.status_code)
    except Exception as e:
        print(f"❌ Failed to forward delete for {phone}: {e}")
        raise HTTPException(status_code=500, detail="Delete forwarding failed")


# -----------------------------------------------------------------------------
# WhatsApp message ingest (existing flow)
# -----------------------------------------------------------------------------
@app.post("/api/ingest-user")
async def ingest_user_groups(data: dict, _: None = Depends(verify_token)):
    logger.info(f"Ingesting parsed data: {data}")
    print("ingesting parsed data: ", data)
    try:
        user = get_user(data["user_id"])
        print("user: ", user)
    except Exception as e:
        print(f"❌ Failed to get user: {e}")
        return {"status": "error", "error": str(e)}

    try:
        if user is None:
            user = create_user(data["user_id"], "", "", "")
    except Exception as e:
        print(f"❌ Failed to create user: {e}")
        return {"status": "error", "error": str(e)}

    try:
        user.runtime.name2chat_id = data["chats"]
        user.runtime.recent_chats = dict(list(data["chats"].items())[:RECENT_CHATS_LIMIT])
        print("user runtime: ", user.runtime)
    except Exception as e:
        print(f"❌ Failed to update name2chat_id: {e}")
        return {"status": "error", "error": str(e)}

    try:
        user_store = UserStore(data["user_id"])
        user_store.save(user)
    except Exception as e:
        print(f"❌ Failed to save user: {e}")
        return {"status": "error", "error": str(e)}

    adapter = CloudAPIAdapter()
    await adapter.send_template_360dialog(data["user_id"], "welcome")
    return {"status": "ok", "groups_ingested": len(data["chats"])}


@app.post("/api/whatsapp/message")
async def receive_whatsapp_message(
    request: Request,
    _: None = Depends(verify_token),
    x_signature: str = Header(...),
):
    logger.info("Received WhatsApp message")
    body = await request.body()
    expected_sig = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_sig, x_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    data = await request.json()
    tracer = Tracer()
    tracer.log_event("whatsapp_message_raw", data=data)

    try:
        whatsappMessage = WhatsAppMessage(**data)
    except ValidationError as e:
        print("❌ Invalid WhatsAppMessage:", e)
        raise HTTPException(status_code=422, detail=e.errors())

    userId = whatsappMessage.chat_id.split("@")[0]

    if whatsappMessage.media and whatsappMessage.media.mimetype.startswith("audio/"):
        filename = save_audio_base64_to_file(whatsappMessage.media)
        if filename:
            user = get_user(userId)
            if user is None:
                return (
                    "תודה רבה אבל עלייך להירשם למערכת לפני שימוש ראשון. "
                    "אנא הירשם בכתובת https://inme-1.onrender.com/login?user_id=" + userId
                )
            whatsappMessage.message = transcribe_opus_file(
                filename, list(user.runtime.recent_chats.keys())
            )

    print("text: ", whatsappMessage.message)
    result = await handleUserInput(whatsappMessage, userId)
    await send_message_to_bot(result, whatsappMessage.bot_identity.phone_number, whatsappMessage.chat_id)
    # tracer.log_event("whatsapp_message_result", data=result)
    return {"status": "ok"}

from shared.user import getUserIds
from green_api.contacts import get_all_contacts
import time

def refresh_contacts():
    userIds = getUserIds()
    for userId in userIds:
        try:
            refresh_contact(userId)
        except Exception as e:
            print(f"❌ Failed to refresh contact for {userId}: {e}")
    
def refresh_contact(userId):
    print("Refreshing contact")
    all_start = time.perf_counter()
    user = get_user(userId)
    if user is None:
        return
    print(f"\nUser: {userId}")
    u_start = time.perf_counter()

    t0 = time.perf_counter()
    try:
        user.runtime.green_api_contacts = get_all_contacts(user.user_id)
    
        t1 = time.perf_counter()
        print(f"  contacts: count: {len(user.runtime.green_api_contacts)} time: {t1 - t0:.3f}s")
        user.runtime.name2chat_id = user.runtime.green_api_contacts
        t4 = time.perf_counter()
        UserStore(user.user_id).save(user)
        t5 = time.perf_counter()
        print(f"  save:     {t5 - t4:.3f}s")

        print(f"  total:    {t5 - u_start:.3f}s")
    except Exception as e:
        print(f"❌ Failed to get contacts for {userId}: {e}")
    
    print(f"\nAll users total: {time.perf_counter() - all_start:.3f}s")

#refresh_contacts()
from shared.user import build_name_to_chat_id
user = get_user("972546610653")
#print("name_to_chat_id: ", name_to_chat_id)

# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("bot:app", host="0.0.0.0", port=port)
