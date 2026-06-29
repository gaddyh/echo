"""
assistant/glue.py — orchestration logic extracted from agents/main.py.

Parses input_source prefix, builds the user prompt, calls the LangGraph agent,
tracks token usage + metrics, and returns the final reply string.
"""
from __future__ import annotations

import os
import time as pytime
from typing import Any

from shared import time as time_utils
from shared.result import getAgentMessage
from shared.token_tracker import TokenTracker
from shared.observability.metrics import track_agent_run
from shared.time import utcnow
from domain.inbound import InboundMessage, UserContext

LLM_PRICE_PER_M_TOKEN = float(os.getenv("LLM_PRICE_PER_M_TOKEN", "6.00"))
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "gpt-4_1")
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://inme-1.onrender.com")

_tracker = TokenTracker()

USER_PROMPT = """
Context:
Now is: {now}
Input source: {input_source}

User message:
{user_message}
"""


def _session_id_for(user_id: str) -> str:
    return f"{user_id}-{int(pytime.time() // 1800)}"


def _count_tool_msgs(messages) -> int:
    count = 0
    for m in messages or []:
        try:
            if isinstance(m, dict):
                role = (m.get("role") or m.get("type") or "").lower()
                if role == "tool" or "tool" in m:
                    count += 1
            else:
                role = getattr(m, "role", "") or getattr(m, "type", "")
                if str(role).lower() == "tool":
                    count += 1
        except Exception:
            continue
    return count


async def run(agent: Any, msg: InboundMessage, ctx: UserContext, services: dict) -> str:
    """
    Invoke *agent* with *msg* / *ctx* / *services* and return the final reply string.

    services must contain keys: "scheduling", "messaging", "user_ctx".
    """
    from shared.user import get_user

    user_id = msg.user_id
    start_time = pytime.time()
    sess_id = _session_id_for(user_id)

    user = get_user(user_id)
    if user is None:
        return (
            "תודה רבה אבל עלייך להירשם למערכת לפני שימוש ראשון. "
            f"אנא הירשם בכתובת {APP_BASE_URL}/login?user_id={user_id}"
        )

    text = msg.text or ""
    if text.startswith("stt:"):
        input_source = "stt"
        clean_text = text[len("stt:"):].strip()
    elif text.startswith("text:"):
        input_source = "text"
        clean_text = text[len("text:"):].strip()
    else:
        input_source = "text"
        clean_text = text.strip()

    user_prompt = USER_PROMPT.format(
        now=time_utils.to_user_timezone(time_utils.utcnow()).strftime("%Y-%m-%d %H:%M:%S"),
        user_message=clean_text,
        input_source=input_source,
    )

    invoke_input = {"messages": [{"content": user_prompt, "role": "user"}]}

    configurable = {
        "user_id": user_id,
        "user_name": msg.sender_name,
        "thread_id": user_id,
        "name2chat_id": ctx.name2chat_id if ctx else user.runtime.name2chat_id,
        "contacts": {},
        **services,
    }

    try:
        result = await agent.ainvoke(invoke_input, {"configurable": configurable})
    except Exception:
        duration_ms = int((pytime.time() - start_time) * 1000)
        track_agent_run(
            user_id=user_id, model=LLM_MODEL_NAME, tokens_total=0,
            latency_ms=duration_ms, tools_invoked_count=0, cost_usd=0.0,
            ok=0, session_id=sess_id,
        )
        raise

    duration = pytime.time() - start_time
    duration_ms = int(duration * 1000)
    print(f"⏱ Agent run duration: {duration:.2f} seconds")

    tokens_used = _tracker.estimate_tokens(result.get("messages"))
    print(f"Tokens used: {tokens_used}")

    current_month = utcnow().strftime("%Y-%m")
    services["user_ctx"].save_token_usage(user_id, current_month, tokens_used)
    print(f"Token delta saved for month {current_month}: +{tokens_used}")

    tools_count = _count_tool_msgs(result.get("messages"))
    cost_usd = (tokens_used / 1_000_000.0) * LLM_PRICE_PER_M_TOKEN
    track_agent_run(
        user_id=user_id, model=LLM_MODEL_NAME, tokens_total=int(tokens_used),
        latency_ms=duration_ms, tools_invoked_count=int(tools_count),
        cost_usd=float(cost_usd), ok=1, session_id=sess_id,
    )

    return getAgentMessage(result)
