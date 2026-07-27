"""
API-level integration tests for the FastAPI backend.

Tests key endpoints using TestClient against the current REST API
(/voice-profiles, /generations, /library):
- POST /voice-profiles: rejects when consent_confirmed=False or name is empty
- GET /voice-profiles: returns a list
- DELETE /voice-profiles/{id}: 404 for a non-existent profile
- POST /generations: rejects empty text and unknown voice profiles
- GET /library: returns a list
- GET /generations/{id}/audio: 404 for a non-existent generation
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


# ── /voice-profiles ─────────────────────────────────────────────────────

def test_create_voice_profile_rejects_without_consent():
    """POST /voice-profiles must return 400 when consent_confirmed=False."""
    response = client.post(
        "/voice-profiles",
        data={"name": "Test Voice", "consent_confirmed": "false"},
        files={"audio": ("test.wav", b"fake-audio-data", "audio/wav")},
    )
    assert response.status_code == 400
    assert "consent" in response.json()["detail"].lower()


def test_create_voice_profile_rejects_empty_name():
    """POST /voice-profiles must return 400 when name is blank."""
    response = client.post(
        "/voice-profiles",
        data={"name": "   ", "consent_confirmed": "true"},
        files={"audio": ("test.wav", b"fake-audio-data", "audio/wav")},
    )
    assert response.status_code == 400
    assert "name" in response.json()["detail"].lower()


def test_list_voice_profiles_returns_list():
    """GET /voice-profiles should always return a JSON list."""
    response = client.get("/voice-profiles", params={"saved": "true"})
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_delete_nonexistent_voice_profile():
    """DELETE /voice-profiles/{id} should return 404 for an unknown profile."""
    response = client.delete("/voice-profiles/nonexistent-id-12345")
    assert response.status_code == 404


# ── /generations ─────────────────────────────────────────────────────────

def test_create_generation_rejects_empty_text():
    """POST /generations must return 400 when text is empty/whitespace."""
    response = client.post(
        "/generations",
        data={"voice_profile_id": "some-id", "text": "   ", "language": "en"},
    )
    assert response.status_code == 400
    assert "text" in response.json()["detail"].lower()


def test_create_generation_rejects_nonexistent_profile():
    """POST /generations should return 404 for a non-existent voice profile."""
    response = client.post(
        "/generations",
        data={"voice_profile_id": "nonexistent-id", "text": "Hello world", "language": "en"},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_download_nonexistent_generation_audio():
    """GET /generations/{id}/audio should return 404 for an unknown generation/job id."""
    response = client.get("/generations/nonexistent-id/audio")
    assert response.status_code == 404


# ── /library ──────────────────────────────────────────────────────────────

def test_list_library_returns_list():
    """GET /library should always return a JSON list."""
    response = client.get("/library")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

