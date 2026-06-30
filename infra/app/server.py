import os
import logging
import asyncio
import contextlib

from contextlib import asynccontextmanager
from typing import Optional
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from store.user import UserStore
from adapters.whatsapp.dialog360.webhook import dialog360_router
from shared.google_calendar.oauth import google_router
from shared.google_calendar.calendar import calendar_router, contacts_router
from adapters.whatsapp.cloudapi.cloud_api_adapter import CloudAPIAdapter
from db.base import db

from adapters.whatsapp.dialog360.webhook import dialog360_router

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

from google.cloud import firestore
import asyncio, datetime
from green_api.instance_mng.create import pool_create_instance
from shared.event_trigger import trigger_events_loop

POOL_SIZE = int(os.getenv("POOL_SIZE", "1"))
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

app = FastAPI(lifespan=lifespan)
app.include_router(dialog360_router)
app.include_router(google_router)
app.include_router(calendar_router)
app.include_router(contacts_router)

templates = Jinja2Templates(directory="apps/templates")

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
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

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("infra.app.server:app", host="0.0.0.0", port=port)
