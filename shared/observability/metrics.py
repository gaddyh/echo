# shared/observability/metrics.py
from __future__ import annotations

import os
import json
import uuid
import time
import hashlib
import logging
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

# ---- Config via env ---------------------------------------------------------
GA4_MEASUREMENT_ID = os.getenv("GA4_MEASUREMENT_ID", "G-3TCPEBSVFJ").strip()
GA4_API_SECRET = os.getenv("GA4_API_SECRET", "_nkIFvEoRnivcg0fRI6V1A").strip()
GA4_COLLECT_URL = os.getenv("GA4_COLLECT_URL", "https://www.google-analytics.com/mp/collect")
GA4_DEBUG = os.getenv("GA4_DEBUG", "0") == "1"  # set to "1" in staging to mark events debug_mode=1
GA4_CLIENT_SALT = os.getenv("GA4_CLIENT_SALT", "echo_salt")  # used if client_id not provided

logger = logging.getLogger(__name__)


# ---- Small utils ------------------------------------------------------------
def _require_cfg() -> None:
    if not GA4_MEASUREMENT_ID or not GA4_API_SECRET:
        raise RuntimeError("GA4_MEASUREMENT_ID / GA4_API_SECRET missing")

def _sanitize_value(s: str) -> str:
    # GA4 param values are fine as-is; this is just to normalize model names like "gpt-4.1"
    return s.replace(".", "_").replace("-", "_")

def make_client_id(user_id: str) -> str:
    # Stable, pseudonymous client_id from user_id + salt
    h = hashlib.sha256(f"{GA4_CLIENT_SALT}:{user_id}".encode("utf-8")).hexdigest()[:32]
    return f"c_{h}"

def new_event_id() -> str:
    return str(uuid.uuid4())

def _now_micros() -> int:
    # Only used if you explicitly pass use_server_timestamp=True
    return int(time.time() * 1_000_000)


# ---- Core sender ------------------------------------------------------------
def send_events(
    events: List[Dict[str, Any]],
    *,
    user_id: str,
    client_id: Optional[str] = None,
    use_server_timestamp: bool = False,
    debug_mode: Optional[bool] = None,
) -> bool:
    """
    Send one or more GA4 Measurement Protocol events.
    - events: list of {"name": <str>, "params": {...}}; we will not mutate it.
    - user_id: your opaque internal user id (string).
    - client_id: optional stable id; if not provided we derive from user_id.
    - use_server_timestamp: if True, include timestamp_micros=now (generally omit).
    - debug_mode: if True, adds params.debug_mode=1 on each event; default uses GA4_DEBUG env.
    Returns True if GA accepted (HTTP 204).
    """
    _require_cfg()

    if not client_id:
        client_id = make_client_id(user_id)

    # Copy events so we can inject debug_mode without touching caller data
    dbg = GA4_DEBUG if debug_mode is None else bool(debug_mode)
    evts: List[Dict[str, Any]] = []
    for e in events:
        name = e.get("name")
        params = dict(e.get("params", {}))
        if dbg:
            params["debug_mode"] = 1
        evts.append({"name": name, "params": params})

    body: Dict[str, Any] = {
        "client_id": client_id,
        "user_id": str(user_id),
        "events": evts,
    }
    if use_server_timestamp:
        body["timestamp_micros"] = _now_micros()

    query = urllib.parse.urlencode({"measurement_id": GA4_MEASUREMENT_ID, "api_secret": GA4_API_SECRET})
    url = f"{GA4_COLLECT_URL}?{query}"
    data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            ok = resp.status in (200, 204)
            if not ok:
                logger.warning("GA4 collect non-2xx: %s %s", resp.status, resp.read())
            return ok
    except Exception as e:
        logger.exception("GA4 collect failed")
        return False


# ---- Convenience wrappers for your two events -------------------------------
def track_agent_run(
    *,
    user_id: str,
    model: str,
    tokens_total: int,
    latency_ms: int,
    tools_invoked_count: int = 0,
    cost_usd: float = 0.0,
    ok: int = 1,  # 1 success, 0 failure
    session_id: Optional[str] = None,
    client_id: Optional[str] = None,
    event_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
) -> bool:
    """
    Send an 'agent_run' event. Call after your model returns.
    """
    params = {
        "model": _sanitize_value(model),
        "tokens_total": int(tokens_total),
        "latency_ms": int(latency_ms),
        "tools_invoked_count": int(tools_invoked_count),
        "cost_usd": float(cost_usd),
        "ok": int(ok),
        "event_id": event_id or new_event_id(),
    }
    if session_id:
        params["session_id"] = str(session_id)

    return send_events(
        [{"name": "agent_run", "params": params}],
        user_id=user_id,
        client_id=client_id,
        debug_mode=debug_mode,
    )


def track_stt_transcribed(
    *,
    user_id: str,
    stt_model: str,
    stt_seconds: float,
    cost_usd: float = 0.0,
    ok: int = 1,
    session_id: Optional[str] = None,
    client_id: Optional[str] = None,
    event_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
) -> bool:
    """
    Send an 'stt_transcribed' event. Call after STT succeeds.
    """
    params = {
        "stt_model": _sanitize_value(stt_model),
        "stt_seconds": float(stt_seconds),
        "cost_usd": float(cost_usd),
        "ok": int(ok),
        "event_id": event_id or new_event_id(),
    }
    if session_id:
        params["session_id"] = str(session_id)

    return send_events(
        [{"name": "stt_transcribed", "params": params}],
        user_id=user_id,
        client_id=client_id,
        debug_mode=debug_mode,
    )

# shared/observability/metrics.py

def track_tool_call(
    *, user_id: str, tool: str, op: str, ok: int, latency_ms: int,
    item_type: str | None = None, error_code: str | None = None,
    session_id: str | None = None, extra: dict | None = None   # <— NEW
) -> bool:
    params = {
        "tool": tool,
        "op": op,
        "ok": int(ok),
        "latency_ms": int(latency_ms),
    }
    if item_type: params["item_type"] = item_type
    if error_code: params["error_code"] = error_code
    if session_id: params["session_id"] = str(session_id)
    if extra:
        # only attach simple, low-cardinality values
        for k, v in extra.items():
            if k not in params and isinstance(v, (int, float, str)):
                params[k] = v
    return send_events([{"name": "tool_call", "params": params}], user_id=user_id)


__all__ = [
    "send_events",
    "track_agent_run",
    "track_stt_transcribed",
    "make_client_id",
    "new_event_id",
]
