"""
tests/conftest.py — shared fixtures for integration tests.

All tests here require real credentials in .secrets/ and real env vars.
The entire suite is skipped automatically when .secrets/firebase1.json is absent.
"""
import os
import pytest

# ── Skip guard: ignore the whole suite before any module is imported ──────────
_CREDS_PRESENT = os.path.exists(".secrets/firebase1.json")

def pytest_ignore_collect(collection_path, config):
    """Skip the entire tests/ directory when Firebase credentials are absent.
    Must fire before collection so db.base is never imported."""
    if not _CREDS_PRESENT:
        tests_dir = os.path.abspath("tests")
        if str(collection_path).startswith(tests_dir):
            return True
    return None


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def real_user_id() -> str:
    """A real registered user ID (phone in 972XXXXXXXXX format).
    Set INTEGRATION_TEST_USER_ID env var before running the suite."""
    uid = os.getenv("INTEGRATION_TEST_USER_ID", "")
    if not uid:
        pytest.skip("INTEGRATION_TEST_USER_ID env var not set")
    return uid
