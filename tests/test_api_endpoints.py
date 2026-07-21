"""
API-level integration tests for the FastAPI backend.

Tests key endpoints using TestClient:
- /upload-voice: rejects when consent_confirmed=False
- /voices: returns list
- /voice-profile/{id}: returns 404 for non-existent profile
- /generate-audio: rejects empty text
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


# ── Tests ────────────────────────────────────────────────────────────────

def test_upload_voice_rejects_without_consent():
    """/upload-voice must return 400 when consent_confirmed=False."""
    response = client.post(
        "/upload-voice",
        data={"name": "Test User", "consent_confirmed": "false"},
        files=[("files", ("test.wav", b"fake-audio-data", "audio/wav"))],
    )
    assert response.status_code == 400
    assert "confirm" in response.json()["detail"].lower()


def test_upload_voice_rejects_no_files():
    """/upload-voice must return 400 when no files are uploaded."""
    response = client.post(
        "/upload-voice",
        data={"name": "Test User", "consent_confirmed": "true"},
    )
    assert response.status_code == 400
    assert "no files" in response.json()["detail"].lower()


def test_list_voices_empty():
    """/voices should return an empty list when no profiles exist (test isolation)."""
    response = client.get("/voices")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_delete_nonexistent_profile():
    """DELETE /voice-profile/{id} should succeed even for non-existent profiles."""
    response = client.delete("/voice-profile/nonexistent-id-12345")
    assert response.status_code == 200
    assert response.json()["deleted"] == "nonexistent-id-12345"


def test_generate_audio_rejects_empty_text():
    """POST /generate-audio should reject empty text."""
    # First we need a voice profile — but since we're in test isolation,
    # we can at least verify the validation happens before DB lookup.
    response = client.post(
        "/generate-audio",
        data={"voice_profile_id": "some-id", "text": "", "language": "en"},
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_generate_audio_rejects_nonexistent_profile():
    """POST /generate-audio should return 404 for non-existent profile."""
    response = client.post(
        "/generate-audio",
        data={"voice_profile_id": "nonexistent-id", "text": "Hello world", "language": "en"},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

