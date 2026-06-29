"""
infra/app/wiring.py — single module that creates the service singletons and
binds the EchoAssistant.  Import `assistant` and `user_ctx` from here.
"""
import os as _os

# ── LangSmith tracing (opt-in via env vars) ───────────────────────────────────
# Set LANGCHAIN_TRACING_V2=true and LANGCHAIN_API_KEY=<key> to enable.
# Optionally set LANGCHAIN_PROJECT=<project> (defaults to "default").
if _os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true":
    if not _os.getenv("LANGCHAIN_API_KEY"):
        import warnings
        warnings.warn("LANGCHAIN_TRACING_V2 is set but LANGCHAIN_API_KEY is missing — tracing disabled.")
# LangChain reads these env vars automatically; no further code needed.
# ─────────────────────────────────────────────────────────────────────────────

from infra.services.scheduling_service import SchedulingService
from infra.services.messaging_service import MessagingService
from infra.services.user_context_service import UserContextService
from assistant.runtime import EchoAssistant

scheduling: SchedulingService = SchedulingService()
messaging: MessagingService = MessagingService()
user_ctx: UserContextService = UserContextService()
assistant: EchoAssistant = EchoAssistant(scheduling, messaging, user_ctx)
