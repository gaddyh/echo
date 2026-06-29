"""
conftest.py — root pytest configuration.

Sets env-var defaults so module-level guards don't raise on import.
Firebase/db stubs live in assistant/evals/conftest.py (unit tests only).
Integration tests in tests/ use real modules with real credentials.
"""
import os as _os

_os.environ.setdefault("GREEN_API_PARTNER_TOKEN", "test-token")
_os.environ.setdefault("GREEN_API_PARTNER_API_URL", "https://localhost/test")
_os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")
_os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
_os.environ.setdefault("WEBHOOK_SECRET", "test-webhook-secret")
_os.environ.setdefault("APP_BASE_URL", "https://localhost")
