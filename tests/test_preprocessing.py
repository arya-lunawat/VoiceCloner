"""
Tests for the audio preprocessing pipeline.

Verifies that PreprocessingError is raised for:
- Extremely short / silent clips
- Clips that are mostly silence (low VAD ratio)

Also verifies that a valid audio clip passes preprocessing.
"""
import os
import sys
import json
import struct
import wave
import numpy as np

# Add backend to path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import preprocessing
from preprocessing import PreprocessingError


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_sine_wav(path: str, duration_sec: float = 10.0, frequency: float = 440.0,
                   sample_rate: int = 24000, amplitude: float = 0.5) -> str:
    """
    Generate a simple sine-wave WAV file (simulates clean speech-like audio
    for testing purposes).
    """
    n_samples = int(sample_rate * duration_sec)
    t = np.linspace(0, duration_sec, n_samples, endpoint=False)
    samples = (amplitude * np.sin(2 * np.pi * frequency * t) * 32767).astype(np.int16)

    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())
    return path


def _make_silent_wav(path: str, duration_sec: float = 10.0, sample_rate: int = 24000) -> str:
    """Generate a completely silent WAV file."""
    n_samples = int(sample_rate * duration_sec)
    samples = np.zeros(n_samples, dtype=np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())
    return path


# ── Tests ────────────────────────────────────────────────────────────────

def test_rejects_silent_clip(tmp_path):
    """A completely silent clip should be rejected by preprocessing."""
    silent_path = _make_silent_wav(str(tmp_path / "silent.wav"), duration_sec=10.0)
    
    with pytest.raises(PreprocessingError, match="mostly silence|music|background noise"):
        preprocessing.preprocess_voice_sample(
            silent_path,
            str(tmp_path / "out"),
            "silent_test",
        )


def test_rejects_very_short_clip(tmp_path):
    """A clip that's too short after trimming should be rejected."""
    short_path = _make_sine_wav(str(tmp_path / "short.wav"), duration_sec=1.0)
    
    with pytest.raises(PreprocessingError, match="too short"):
        preprocessing.preprocess_voice_sample(
            short_path,
            str(tmp_path / "out"),
            "short_test",
        )


def test_accepts_valid_clip(tmp_path):
    """A clean sine-wave clip of sufficient duration should pass preprocessing."""
    clip_path = _make_sine_wav(str(tmp_path / "valid.wav"), duration_sec=10.0)
    
    result = preprocessing.preprocess_voice_sample(
        clip_path,
        str(tmp_path / "out"),
        "valid_test",
    )
    
    assert "processed_path" in result
    assert os.path.exists(result["processed_path"])
    assert result["duration_sec"] >= 5.0
    assert result["voiced_ratio"] >= 0.4  # Should have plenty of "voice" activity


def test_rejects_music_low_voice_ratio(tmp_path):
    """A clip with very low voiced ratio (simulating music/noise) should be rejected.

    We generate a high-frequency, low-amplitude noisy signal that VAD
    will likely classify as non-speech.
    """
    n_samples = int(24000 * 10.0)
    # White noise at very low amplitude
    noise = (np.random.randn(n_samples) * 500).astype(np.int16)
    noise_path = str(tmp_path / "noise.wav")
    with wave.open(noise_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(noise.tobytes())

    with pytest.raises(PreprocessingError, match="mostly silence|music|background noise"):
        preprocessing.preprocess_voice_sample(
            noise_path,
            str(tmp_path / "out"),
            "noise_test",
        )


# Need pytest for tmp_path fixture
import pytest

