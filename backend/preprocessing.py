"""
Audio preprocessing pipeline.
Uses only free/open-source libraries: librosa, pydub, webrtcvad, ffmpeg (system binary, free).
"""
import os
import wave
import contextlib
import numpy as np
import librosa
import soundfile as sf
import webrtcvad
from pydub import AudioSegment, silence

TARGET_SR = 24000  # XTTS v2 expects 24kHz mono
MIN_DURATION_SEC = 5.0        # reject clips shorter than this after trimming
MAX_SILENCE_RATIO = 0.6       # reject if mostly silence


class PreprocessingError(Exception):
    """Raised when an uploaded clip fails quality checks and should be rejected."""
    pass


def convert_to_wav(input_path: str, output_path: str) -> str:
    """Convert any supported format (mp3, flac, m4a, wav) to mono 24kHz wav using ffmpeg via pydub."""
    audio = AudioSegment.from_file(input_path)
    audio = audio.set_channels(1).set_frame_rate(TARGET_SR)
    audio.export(output_path, format="wav")
    return output_path


def normalize_volume(audio: AudioSegment, target_dbfs: float = -20.0) -> AudioSegment:
    change = target_dbfs - audio.dBFS
    return audio.apply_gain(change)


def trim_silence(audio: AudioSegment, silence_thresh_db: int = -40, min_silence_len_ms: int = 400) -> AudioSegment:
    chunks = silence.split_on_silence(
        audio,
        min_silence_len=min_silence_len_ms,
        silence_thresh=audio.dBFS + silence_thresh_db,
        keep_silence=150,
    )
    if not chunks:
        return audio
    combined = AudioSegment.empty()
    for chunk in chunks:
        combined += chunk
    return combined


def run_vad_check(wav_path: str) -> float:
    """
    Returns the fraction of frames classified as voiced speech using WebRTC VAD.
    Used to reject clips that are mostly silence, music, or noise.
    """
    vad = webrtcvad.Vad(2)  # aggressiveness 0-3
    with contextlib.closing(wave.open(wav_path, "rb")) as wf:
        sample_rate = wf.getframerate()
        assert sample_rate in (8000, 16000, 32000, 48000), \
            "VAD requires 8/16/32/48kHz - resample a copy for this check"
        pcm_data = wf.readframes(wf.getnframes())

    frame_duration_ms = 30
    frame_size = int(sample_rate * frame_duration_ms / 1000) * 2  # 16-bit samples
    voiced = 0
    total = 0
    for i in range(0, len(pcm_data) - frame_size, frame_size):
        frame = pcm_data[i:i + frame_size]
        total += 1
        if vad.is_speech(frame, sample_rate):
            voiced += 1
    if total == 0:
        return 0.0
    return voiced / total


def check_duration(wav_path: str) -> float:
    y, sr = librosa.load(wav_path, sr=None)
    return librosa.get_duration(y=y, sr=sr)


def preprocess_voice_sample(input_path: str, output_dir: str, filename_base: str) -> dict:
    """
    Full pipeline for one uploaded recording:
    1. Convert to wav
    2. Normalize volume
    3. Trim silence
    4. Voice-activity check (rejects music-only / mostly-silent clips)
    5. Duration check (rejects too-short clips)

    Returns dict with processed path + quality metrics. Raises PreprocessingError on rejection.
    """
    os.makedirs(output_dir, exist_ok=True)

    raw_wav = os.path.join(output_dir, f"{filename_base}_raw.wav")
    convert_to_wav(input_path, raw_wav)

    audio = AudioSegment.from_wav(raw_wav)
    audio = normalize_volume(audio)
    audio = trim_silence(audio)

    processed_path = os.path.join(output_dir, f"{filename_base}_clean.wav")
    audio.export(processed_path, format="wav")

    duration = len(audio) / 1000.0
    if duration < MIN_DURATION_SEC:
        raise PreprocessingError(
            f"Clip too short after trimming ({duration:.1f}s). "
            f"Please upload at least {MIN_DURATION_SEC}s of clear speech."
        )

    # VAD check needs a 16kHz mono copy
    vad_check_path = os.path.join(output_dir, f"{filename_base}_vadcheck.wav")
    y, _ = librosa.load(processed_path, sr=16000, mono=True)
    sf.write(vad_check_path, y, 16000, subtype="PCM_16")
    voiced_ratio = run_vad_check(vad_check_path)
    os.remove(vad_check_path)

    if voiced_ratio < (1 - MAX_SILENCE_RATIO):
        raise PreprocessingError(
            f"Recording appears to be mostly silence, music, or background noise "
            f"(only {voiced_ratio*100:.0f}% detected as clear speech). "
            f"Please upload a clean solo recording of your voice."
        )

    return {
        "processed_path": processed_path,
        "duration_sec": round(duration, 2),
        "voiced_ratio": round(voiced_ratio, 2),
        "sample_rate": TARGET_SR,
    }
