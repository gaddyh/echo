"""
assistant/evals/conftest.py

Stubs for the unit test suite — patches firebase_admin and db.base so
tests run with no real credentials. Env-var defaults are set here too
so the module-level guards in green_api/webhook/etc don't raise on import.
"""
import sys
import types
from unittest.mock import MagicMock

# ── Stub firebase_admin + firestore ──────────────────────────────────────────

_firebase_admin = types.ModuleType("firebase_admin")
_firebase_admin.initialize_app = MagicMock()
_firebase_admin.credentials = MagicMock()
_firebase_admin.credentials.Certificate = MagicMock(return_value=MagicMock())

_firestore_mod = types.ModuleType("firebase_admin.firestore")
_mock_db = MagicMock()
_firestore_mod.client = MagicMock(return_value=_mock_db)
_firebase_admin.firestore = _firestore_mod

sys.modules.setdefault("firebase_admin", _firebase_admin)
sys.modules.setdefault("firebase_admin.credentials", _firebase_admin.credentials)
sys.modules.setdefault("firebase_admin.firestore", _firestore_mod)

# ── Stub db.base ──────────────────────────────────────────────────────────────

_db_base = types.ModuleType("db.base")
_db_base.db = _mock_db
sys.modules["db.base"] = _db_base
sys.modules.setdefault("db", types.ModuleType("db"))
