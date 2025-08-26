# agents/main.py (or wherever your handler lives)

import time as pytime

from shared.user import get_user
from context.message.raw_message import RawMessage
from shared.token_tracker import TokenTracker
from shared.result import getAgentMessage
from store.user import UserStore
from shared.time import utcnow
from shared.user import TokenUsage
from agents.echo.core import echo_agent
from shared import time

# 🔧 NEW: GA4 metrics for agent runs
import os
from shared.observability.metrics import track_agent_run

LLM_PRICE_PER_M_TOKEN = float(os.getenv("LLM_PRICE_PER_M_TOKEN", "6.00"))  # set in prod
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "gpt-4_1")  # used for metrics display

tracker = TokenTracker()

def _session_id_for(user_id: str) -> str:
    # rolling 30-minute session id; good enough for analytics
    return f"{user_id}-{int(pytime.time() // 1800)}"

def _count_tool_msgs(messages) -> int:
    """Best-effort count of tool invocations from the LangGraph/LC message list."""
    count = 0
    for m in messages or []:
        try:
            if isinstance(m, dict):
                role = (m.get("role") or m.get("type") or "").lower()
                if role == "tool" or "tool" in m:
                    count += 1
            else:
                # Some message objects may be non-dicts; try attributes
                role = getattr(m, "role", "") or getattr(m, "type", "")
                if str(role).lower() == "tool":
                    count += 1
        except Exception:
            continue
    return count

USER_PROMPT = """
Context:
Now is: {now}
Input source: {input_source}

User message:
{user_message}
"""

async def handleUserInput(rawMessage: RawMessage, user_id: str) -> str:
    print("handleUserInput")
    start_time = pytime.time()
    sess_id = _session_id_for(user_id)

    user = get_user(user_id)
    if user is None:  # TODO: remove this. ingest creates user !
        return (
            "תודה רבה אבל עלייך להירשם למערכת לפני שימוש ראשון. "
            f"אנא הירשם בכתובת https://inme-1.onrender.com/login?user_id={user_id}"
        )

    # ---- Parse input_source ----
    content_text = rawMessage.content.text or ""
    if content_text.startswith("stt:"):
        input_source = "stt"
        clean_text = content_text[len("stt:"):].strip()
    elif content_text.startswith("text:"):
        input_source = "text"
        clean_text = content_text[len("text:"):].strip()
    else:
        input_source = "text"
        clean_text = content_text.strip()

    # ---- Build prompt with input_source ----
    userPrompt = USER_PROMPT.format(
        now=time.to_user_timezone(time.utcnow()).strftime('%Y-%m-%d %H:%M:%S'),
        user_message=clean_text,
        input_source=input_source,   # 👈 include in SYSTEM_PROMPT context
    )

    input = {
        "messages": [
            {"content": userPrompt, "role": "user"},
        ]
    }

    try:
        result = await echo_agent.ainvoke(
            input,
            {
                "configurable": {
                    "user_id": user_id,
                    "user_name": rawMessage.sender.name,
                    "thread_id": user_id,
                    "name2chat_id": user.runtime.name2chat_id,
                    "contacts": {},
                }
            },
        )
    except Exception:
        # Track failed agent run
        duration_ms = int((pytime.time() - start_time) * 1000)
        track_agent_run(
            user_id=user_id,
            model=LLM_MODEL_NAME,
            tokens_total=0,
            latency_ms=duration_ms,
            tools_invoked_count=0,
            cost_usd=0.0,
            ok=0,
            session_id=sess_id,
        )
        raise

    # ---- Post-run metrics & bookkeeping ----
    duration = pytime.time() - start_time
    duration_ms = int(duration * 1000)
    print(f"⏱ Agent run duration: {duration:.2f} seconds")

    tokensUsed = tracker.estimate_tokens(result.get("messages"))
    print(f"Tokens used: {tokensUsed}")

    current_month = utcnow().strftime("%Y-%m")
    usage = user.runtime.monthlyTokenUsage.setdefault(current_month, TokenUsage())
    usage.total += tokensUsed
    print(f"Total tokens used this month ({current_month}): {usage.total}")
    UserStore(user.user_id).save(user)

    tools_invoked_count = _count_tool_msgs(result.get("messages"))
    cost_usd = (tokensUsed / 1_000_000.0) * LLM_PRICE_PER_M_TOKEN
    track_agent_run(
        user_id=user_id,
        model=LLM_MODEL_NAME,
        tokens_total=int(tokensUsed),
        latency_ms=duration_ms,
        tools_invoked_count=int(tools_invoked_count),
        cost_usd=float(cost_usd),
        ok=1,
        session_id=sess_id,
    )

    final = getAgentMessage(result)
    return final

