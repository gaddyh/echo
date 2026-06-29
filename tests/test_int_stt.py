"""
tests/test_int_stt.py

Verifies Google Cloud Speech-to-Text integration.
Requires a small .opus fixture file at tests/fixtures/test_audio.opus
(not checked into git — place a real Hebrew voice clip there before running).

Skipped automatically if the fixture file is absent.
"""
import os
import pytest
from shared.google_tts import transcribe_opus_file

pytestmark = pytest.mark.integration

FIXTURE_PATH = "tests/fixtures/test_audio.opus"
_has_fixture = os.path.exists(FIXTURE_PATH)


@pytest.mark.skipif(not _has_fixture, reason=f"STT fixture not found at {FIXTURE_PATH}")
def test_stt_returns_nonempty_transcript():
    """Transcription of a real audio clip returns a non-empty string."""
    result = transcribe_opus_file(FIXTURE_PATH, [])
    assert isinstance(result, str)
    assert len(result.strip()) > 0, "STT returned empty transcript"


@pytest.mark.skipif(not _has_fixture, reason=f"STT fixture not found at {FIXTURE_PATH}")
def test_stt_with_phrase_hints():
    """Phrase hints don't cause a crash and still return a result."""
    result = transcribe_opus_file(FIXTURE_PATH, ["שלום", "תזכיר", "פגישה"])
    assert isinstance(result, str)


def test_stt_credentials_file_exists():
    """The Google Speech credentials file is present on disk."""
    secrets_dir = os.getenv("SECRETS_DIR", ".secrets")
    creds_file = os.getenv("GOOGLE_SPEECH_CREDENTIALS", "tami-463501-a8053925ce03.json")
    full_path = os.path.join(secrets_dir, creds_file)
    assert os.path.exists(full_path), (
        f"STT credentials not found at {full_path}. "
        "Set GOOGLE_SPEECH_CREDENTIALS env var or place the file in .secrets/"
    )
